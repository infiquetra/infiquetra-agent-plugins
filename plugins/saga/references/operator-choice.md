# Operator-Choice Framework

**Status:** canonical contract · **plugin version:** 0.5.0
**Companion:** [`references/saga-spec.md`](./saga-spec.md) — the **STORAGE** contract for the chosen value.
**Audience:** every lifecycle command that runs work or routes work (`/work`, and the rest)
implements against this file when deciding *how* work executes.

This is the **DECISION contract** for the execution backend in saga. Where
`saga-spec.md` says *how the choice is stored* (the `orchestration_mode` / `orchestration_ref` fields), this
document says *how the choice is made*. Lifecycle owns the **CHOICE**, not the execution.

> The CLI-backed execution-backend helper **shipped with the `/work` rebuild**: `recommend_execution_backend()`
> lives in [`scripts/lifecycle_state.py`](../scripts/lifecycle_state.py) (the `recommend-backend` subcommand).
> `/work` has called it since 0.10.0. `/loop` was its second caller until issue 1030 removed that
> command; the helper itself survives, and since the same issue archived every backend above
> `inline` it returns `inline` with a work-shape rationale rather than a choice.

---

## 1. The one selectable execution backend

> **Issue 1030 narrowed this menu to one.** `ORCHESTRATION_MODES` in
> [`scripts/saga.py`](../scripts/saga.py) is now `("inline",)`. The `team-execution` plugin was
> archived and the `cc-workflows` plugin was removed, so neither backend is installed and neither
> can be selected. **Sections 3, 4 and 8 below are a historical record** of how the three-way menu
> was offered; read them to understand a saga written before the release, not to make a choice
> today. Sections 1 and 2 are current. Sections 5, 6 and 7 are current about the transport and the
> storage, and they name `/loop`, `/resume`, `/optimize` and `/outcome` as writers and consumers.
> All four were removed by the same issue, so read each such row as a record of which command wrote
> a field, never as a command to run.

There is exactly one selectable enum value: the stored `orchestration_mode` a new run writes is
`inline`. That string is the contract, and it matches `ORCHESTRATION_MODES` in
[`scripts/saga.py`](../scripts/saga.py) and §4 of `saga-spec.md`. Prose labels people say out loud
("CC workflows", "ultracode", "team mode") were never the contract; only the enum strings were.

**Two strings still read back and are never written.** `team-execution` and
`cc-workflows-ultracode` remain a frozen wire contract: a saga tick recorded before the release
still carries one, still loads, and still renders its label through
`ORCHESTRATION_MODE_LABELS`. `_orchestration_rank` returns `None` for either, which is what keeps
the provenance guard lenient on history while `saga.py` refuses the value at the command line,
where a *new* choice is being made.

| Backend (enum) | What it is | Owns execution? | Availability |
|---|---|---|---|
| `inline` | The agent does the work itself, single-context / serial. **The only value a new run writes.** | the agent | always |
| `team-execution` | The archived team-execution plugin's worker / reviewer / validator run. | — | **archived (issue 1030)**; readable at rest, never selectable |
| `cc-workflows-ultracode` | The Claude Code **Workflow** tool's deterministic multi-agent orchestration. | — | **removed (issue 1030)**; readable at rest, never selectable |

What the archived backend provided — reviewer consensus and named scanners — is now the lensed
code review and the build loop's mechanical baseline, both of which an inline run already performs.

**Ownership boundary.** Lifecycle **chooses**; the backends **execute**. `deploy` is **offered, not
vendored** — lifecycle never reimplements its machinery, it points to it and records the pointer. A
saga holds the choice (`orchestration_mode`) and a pointer into the backend
(`orchestration_ref`); it is never the execution authority.

---

## 2. Who decides

The operator decides; lifecycle makes the cheapest-correct path one keystroke away. With one
selectable value there is no menu left to render, so what remains of this section is the *rationale*
a run records, not a question it asks.

- **inline, always.** Work runs `inline`. No ceremony, and no offer, because there is nothing to
  offer against.
- **The work shape still selects a rationale.** `recommend_execution_backend` in
  [`scripts/lifecycle_state.py`](../scripts/lifecycle_state.py) still computes the size, risk and
  gated-consensus signals §3 describes. They no longer pick a different backend; they choose which
  sentence the run records about why it ran the way it did, which is worth keeping.
- **Operator override is still the operator's.** A recorded value is whatever the operator set. An
  operator who explicitly invokes a Claude Code Workflow inside their own session is doing something
  task-local; it is not a saga backend, and saga does not record one for it.

---

## 3. When to escalate (triggers) — historical

> **Historical since issue 1030.** Both backends this section escalates to are gone: the
> `team-execution` plugin is archived and the `cc-workflows` plugin is removed. The
> signals below are still computed in `lifecycle_state.py`, but they now select the
> rationale a run records rather than a different backend (§2). Read this to understand a
> saga written before the release.

### 3.1 `inline` -> `team-execution`

This mirrors `should_offer_team_execution` in
[`scripts/lifecycle_state.py`](../scripts/lifecycle_state.py) — **that function is the canonical trigger
source; keep these numbers — and the `has_code_surface` docs-gating below — identical to its constants.**
Offer `team-execution` when **ANY** of:

| Signal | Threshold |
|---|---|
| `file_count` | `>= 8` |
| `phase_count` | `>= 4` |
| `has_security` | true |
| `has_infra` | true |
| `cross_repo` | true |
| `deployment_sensitive` | true |

**OR** a **GATED** needs-consensus signal — see the governance split below. team-execution's whole value
is *review consensus + gates*, so a job that wants a verdict to **block and persist** is a team-execution
job even if it is small — a gated consensus signal is **sufficient on its own**, not an additive PLUS
(this matches `recommend_execution_backend`, which ORs the gated half in).

**Gated vs advisory consensus (the governance split, R7).** A bare "needs consensus" is not enough — the
deciding question is whether the verdict **needs to stick**:

| Consensus shape | What it means | Backend |
|---|---|---|
| **gated** (`consensus_is_gated=True`, the default) | the verdict must BLOCK a merge/deploy and PERSIST as standing evidence — a reviewer-CONSENSUS gate, named scanners, a guarded deploy | `team-execution` |
| **advisory** (`consensus_is_gated=False`) | N throwaway in-session votes the operator acts on themselves; nothing is recorded or blocks | `inline`. A Claude Code Workflow judge-panel is allowed only by **explicit invocation** (§3.2 adversarial confidence), never as the automatic advisory path. |

So `recommend_execution_backend` no longer hard-forces team-execution on *every* consensus signal: only
**gated** consensus reaches team-execution. **Advisory** consensus stays on `inline` in the default Saga
offer; a Workflow judge-panel is **explicit invocation only** (§3.2), never the automatic advisory path.
When advisory consensus AND a broad fan-out both fire, the default offer is still the Saga pair
(`inline` / `team-execution`), not a third interchangeable Workflow choice (§3.3). `/plan` resolves the
gated/advisory question with the KTD4 interrogation question (`skills/plan/SKILL.md` §5.2), defaulting
to *gated* when deploy/security/persist signals are present and *advisory* otherwise — the operator
confirms.

**Docs exception (`has_code_surface=False`).** team-execution's scanners + deploy gate are code-shaped and
inert on pure docs/spec/research output, so the **output-blind** rows above — `file_count`, `phase_count`,
`has_security`, `has_infra`, `deployment_sensitive` (the last two are `parse_issue.py` keyword matches that
fire on a doc merely *mentioning* terraform or auth) — are neutralized when the work has no code/ship
surface. Two rows survive because they signal governance, not code: **`cross_repo`** (crossing a repo =
crossing an ownership boundary = a multi-party coordination need) and the **gated** needs-consensus signal
(advisory consensus routes to ultracode regardless of code surface). A big docs change with neither stays
`inline`/ultracode, not team-execution.

### 3.2 `inline` -> `cc-workflows-ultracode` (Claude Code only)

**Explicit invocation only — never a default offer.** An operator may explicitly invoke a Claude Code
Workflow when the work matches **any** of the frozen `workflow_shapes` vocabulary — **understand / design /
research / review / migrate**, the shapes the Workflow tool doc itself names — or either of the two
legacy ungoverned-multiplicity triggers still recognized beside them, all without elevated risk. These
purposes describe when that invocation is *useful*. They do **not** auto-select, pre-select, or add
`cc-workflows-ultracode` as a generic interchangeable third backend:

- **Breadth / scale** (`broad_independent_fanout`) — high-parallelism, broad independent fan-out (the
  same operation across many targets), or an exhaustive search-all / probe-all sweep where missing a
  target is the failure mode.
- **Adversarial confidence** (`adversarial_confidence`) — prove-by-refutation, a judge panel over N
  independent attempts, or perspective-diverse verifiers each applying a distinct lens. This is real review
  depth; the Workflow tool names *confidence* as a first-class purpose. Set it only on an **explicit**
  request for many-independent-attempt verification — not inferred from a generic "be more sure," and not
  when 1-3 lenses suffice (that is an `inline` / `team-execution` review, not an ultracode fan-out).
- **Named workflow shape** (`workflow_shapes`, repeatable) — a request that matches one of the five frozen
  shapes: **understand** (broad codebase/system comprehension), **design** (structured option exploration),
  **research** (multi-source investigation), **review** (a multi-lens review *sweep* requested as a
  workflow — the explicit refute-N / judge-panel form stays `adversarial_confidence`, and the two may
  co-fire with no precedence between them), or **migrate** (a systematic many-target transformation). An
  unknown shape is rejected loud (`ValueError`), never silently downgraded to `inline`.

So ultracode is **not** "fan-out, not review depth" — it delivers deterministic fan-out **and** independent
adversarial verification. What it lacks is **governance**: no reviewer-CONSENSUS gate, no named scanner
registry, no guarded deploy. That — not "review depth" — is the line to `team-execution` (§3.1).

**The mechanical boundary** (artifact kind, not ceremony level): ultracode gives a *throwaway* confidence
signal on a finding you then act on yourself — N votes, the run ends, nothing is recorded or blocks.
team-execution gives a *standing* verdict — a consensus score that blocks downstream scanners and the deploy
and persists as evidence. Want independent cross-checking of a read-only finding → an **explicitly invoked**
Workflow. Need the review to gate a merge/deploy or be recorded → team-execution. A job that is both risky
**and** wide still offers the Saga pair (`team-execution` / `inline`) — §3.3 — and enters a Workflow only
if the operator explicitly invokes one.

### 3.3 Overlap (both fire)

A large security audit is legitimately *both* risky **and** parallel — both triggers fire. When that
happens, **OFFER the Saga pair** (`team-execution` first, `inline` as the cheaper alternative) and let
the operator pick. Do **not** add `cc-workflows-ultracode` as a third interchangeable choice. There is
**no hard precedence rule** between the two Saga backends: because the offer always confirms with the
operator, any precedence would be cosmetic. The operator resolves the overlap. A Workflow remains
available only by explicit invocation.

Recommended-default rule of thumb (which one to pre-select):

| Work shape | Lean |
|---|---|
| risky **and** parallel | `team-execution` |
| parallel **and** not risky | `inline` (Workflow only by explicit invocation) |
| neither | `inline` |

---

## 4. Capability gate (`cc-workflows-ultracode` is Claude Code only) — historical

> **Historical since issue 1030.** `cc-workflows-ultracode` is no longer a saga backend,
> so there is no capability to gate. The host-portability rule this section states —
> halt rather than silently substitute a backend the host cannot run — is the part worth
> keeping, and it survives in `recheck_orchestration_capability`.

This plugin runs on hosts **without** the Workflow tool (e.g. redis-channel sessions, other runners). Two
rules keep the contract honest across hosts:

- **Document all three enum values ALWAYS.** This file is the full map; an off-host reader needs to
  understand `cc-workflows-ultracode` even though they cannot run it.
- **At the default offer, name the two Saga backends.** Do not treat `cc-workflows-ultracode` as a
  third interchangeable choice, available or not. When the operator has **explicitly invoked** a
  Workflow, probe availability (`probed` via `ToolSearch`, or `asserted` when a live probe wasn't
  possible) and HALT rather than silently substituting `inline` or `team-execution` if the tool is
  absent. An `asserted` absence renders as "unverified; probe before trusting".

**If `cc-workflows-ultracode` was explicitly invoked but turns out to be unavailable,** HALT with a
recovery line pointing at `team-execution` or `inline` — do not silently substitute. `/work` Phase 1.5
owns that halt. `/loop`'s own phase-walk is the cross-host fallback when no heavier Saga backend is
reachable.

---

## 5. How to offer (dual form)

The offer renders differently depending on the surface, because not every surface can call
`AskUserQuestion`:

- **Claude Code session** — use `AskUserQuestion` with the **recommended Saga backend pre-selected**
  (`inline` or `team-execution`; §2, §3.3). Do not pre-select `cc-workflows-ultracode`.
- **redis-channel session** — `AskUserQuestion` **cannot** be called; inline **lettered choices** in the
  reply text instead ("Which backend? A) inline … B) team-execution …"). A Claude Code Workflow is not
  a default letter; it is entered only when the operator explicitly names it. Follow
  the canonical channel-inline convention documented in
  [`skills/brainstorm/SKILL.md`](../skills/brainstorm/SKILL.md) — **reference it; do not duplicate its
  wording here.** That doc is the single source for how channel-inline choices are phrased.

### 5.1 Channel-transport gate delivery — the `/outcome` R20 approval gate (#379)

The **same channel-inline shape** delivers the one durable-record operator gate — the `/outcome` R20
frontier-approval gate — to a keyboard-less operator, so a gate that fires while the terminal is
unattended can still be answered over redis-channel / Discord. This is a *transport for an existing
gate*, never a new gate mechanism (`{#operator-choice-framework}`). It applies **only** to the
`/outcome` gate (the only gate with a durable structured record, `approvals/r{rev}.json`); the
per-skill `AskUserQuestion` gates (`/work` merge, `/plan`, …) inline their choices as in §5 but have no
durable channel-answer record — a durable per-skill gate record is deferred follow-up, not this
contract.

**Notice (session → operator).** When an `/outcome` gate holds a frontier and a channel session is
connected, the session renders the prompt with
`outcome_gate_transport.compose_gate_notice(spec, spec_revision, gated_subplots)` and sends it over the
**connected transport's** `reply()` (redis-channel `reply()` for a redis session; the Discord `reply()`
MCP tool for Discord). The notice carries a **gate id** — `<outcome_id>@r<spec_revision>` — that the
answer must quote.

**Answer (operator → session).** The operator's reply arrives as an ordinary `<channel …>` inbound.
The session recognizes a gate answer with the pure helper
`outcome_gate_transport.parse_gate_answer(inbound, pending_gate_ids)` and, on an `approve` verdict, records the approval through the coordinator's own approve command, passing the answerer and the transport as provenance.

> The command this section used to spell out was `outcome.py approve`, and issue 1030 removed
> that script with the `/outcome` command. The transport shape is what this section documents and
> it outlived the coordinator; the exact argument line did not, so it is described rather than
> quoted.

This is **doc-only + CLI-driven** (`{#operator-choice-framework}`): no background daemon parses the
channel; the session recognizes the reply and invokes the CLI, exactly as it does for a channel-inline
backend choice.

**Access is the transport's, never a new allowlist (option A, KTD2).** Sender authorization is enforced
**upstream of the session** by the transport's own access policy — Discord `gate()` pre-filters inbound
to `allowFrom` before the session sees it; redis-channel defers to its router
([[feedback_redis_channel_router_agnostic]]). `parse_gate_answer` therefore records the *already
authorized* `answerer` / `transport` as **provenance** (read from the router-set inbound fields, never
the message body) and accepts a reply **only** when it quotes a gate id that is in the current
`pending_gate_ids` set. A reply that matches no pending gate, is unattributable, or is verdict-ambiguous
is **not accepted** and is surfaced — the parser never defaults to *approve*. A channel message thus
cannot forge or escalate an approval: authority derives from the upstream gate the sender already
passed, exactly as the existing scoped permission-reply pattern does.

---

## 6. Recording the choice

**Durable home:** the saga envelope — `orchestration_mode` (the enum value, §1) plus `orchestration_ref` (a
pointer into the chosen backend). See [`references/saga-spec.md`](./saga-spec.md) for the storage contract
(field table §3.1, enum domain §4).

**Saga writers.** `/plan` (0.7.0), `/work` (0.10.0), and `/loop` (0.11.0) write sagas — they record the chosen
backend durably via the saga's `--orchestration-mode` field. `/loop` records the backend for **`/loop`-owned
work only**: in Drive mode it ticks the chosen backend onto the work-thread saga (the routing tick carries the
offload pointer only for `/loop`-owned offloads); when `/loop` *routes* to another command it does **not**
instruct or record that command's backend (each command owns its own backend decision — `/work`, e.g., writes
but never reads `orchestration_mode`). A command that does not yet write a saga records the backend
**NARRATIVELY**; it must not call `saga.save` until its rebuild wires it as a real consumer.

`orchestration_ref` by backend:

| `orchestration_mode` | `orchestration_ref` |
|---|---|
| `inline` | empty string `""` |
| `team-execution` | the team name |
| `cc-workflows-ultracode` | the **spec JSON path** (durable, set at `/plan` tick time); the workflow run handle rides in `orchestration_run_id` (#693), never here |

**`cc-workflows-ultracode` ref lifecycle.** At `/plan` time, `orchestration_ref` is set to the **canonical
spec JSON** (`docs/workflows/<date>-<topic>-spec.json`). The `.workflow.js` is a derived artifact — regenerable
at any time via `execution_spec.py emit <spec.json>` — so the spec JSON is the durable pointer. When `/work`
subsequently launches the Workflow tool and receives a workflow id, it records that id in a second saga tick
as **`orchestration_run_id`** — never as `orchestration_ref` (#693: overwriting the ref destroyed the spec
path the same launch had just read, leaving the next resume nothing to locate the spec with). The spec JSON
is therefore always the canonical authoring artifact and the workflow id the transient execution handle, and
the two coexist on one saga. `saga.py spec-check` discriminates the ref at launch/resume time — a run id in
the ref, an empty ref, or a missing spec file is a HALT, not a silent misdelivery.

**The halt-not-degrade guarantee.** A `cc-workflows-ultracode` choice is a **guarantee-bearing** commitment —
the operator chose parallel fan-out **and** refute-N adversarial verification. `/work` honors this guarantee by
halting rather than silently degrading when execution is impossible in the current session:

- **Workflow tool absent:** HALT with a recovery line pointing to a capable session or a backend switch.
- **Spec ref not `ok` (`saga.py spec-check`, #693):** HALT with a recovery line pointing back to `/plan` to
  author the spec (or re-record the spec path when the ref holds a stale run id).

This halt-not-degrade rule is **explicitly NOT** the off-host recompile-down path
(`recheck_orchestration_capability` in `lifecycle_state.py`), which is reserved for `/loop`'s phase-walk
fallback and `/resume`'s capability probe — both of which run in a polling/recovery context where the operator
is absent. `/work`, by contrast, runs with the operator present and can surface the halt for a real decision.
Silently substituting hand-rolled sequential subagents would lose the parallel fan-out and refute-N panels
that make the `cc-workflows-ultracode` choice meaningful (the campps issue-38 failure). The
**provenance guard** in `saga.py save` backstops this: a tick where
`orchestration_mode != orchestration_operator_choice` with no `orchestration_downgrade` note is rejected, so
`/work` cannot cover a secret substitution by rewriting `operator_choice`.

---

## 7. Consumer contract (who cites this, when)

Each command cites this file at its own rebuild. The CLI-backed execution-backend helper
(`recommend_execution_backend()`) **shipped with the `/work` rebuild** (0.10.0); `/work` is its first caller.

| Command | Cites operator-choice |
|---|---|
| `/loop` | **now** (prose offer hook + saga writer for `/loop`-owned work + the CLI-backed `recommend_execution_backend()` helper, since 0.11.0) |
| `/work` | **now** (prose offer hook + the CLI-backed `recommend_execution_backend()` helper, shipped 0.10.0) |
| `/plan` | at its rebuild |
| `/resume` | at its rebuild |
| `/code-review` | at its rebuild |
| `/founder-review` | at its rebuild |
| `/qa` | at its rebuild |
| `/investigate` | **now** (saga read-only; offers a backend for large/parallel fixes + parallel hypothesis-probes, since 0.16.0) |
| `/retro` | at its rebuild |
| `/spec` | **never offers** — a single durable spec artifact; size/risk lives in its scope sections, and the downstream executor (/plan / /work) owns backend selection |
| `/optimize` | **now** — offers a backend for independent experiment fan-out (default serial inline); records the choice NARRATIVELY (saga-untouched); since 0.18.0 |
| `/doc-review` | at its rebuild |
| `/strategy` | **never offers** — a single durable doc, no parallelism to escalate |

---

## 8. OutcomeOrchestrator: the full backend menu + the presence-conditional degrade policy (R6/R23) — historical

> **Removed by issue 1030.** The `/outcome` coordinator, `outcome_dispatcher.py` and
> `outcome_liveness.py` all left the plugin with the eleven removed commands. Running one piece of
> work across several sessions is the `orchestrate` plugin's, and it makes its own routing
> decisions. This section is kept as the record of what the wider menu was and why it degraded the
> way it did; nothing in it describes code that is still here.

The backends above were the leaf-saga choice. The OutcomeOrchestrator (the coordinator over a
DAG of leaf sagas) routed EACH leaf through the same seam but over a **wider menu** and added an automatic,
presence-conditional **degrade** decision the single-saga layer did not have.

**The full menu (R6), host-conditional.** `resolve_available()` returns:

- **always-available floor** — `inline` / `team-execution` / `manual` (the operator does it by hand);
- **host-dependent** (only when the host advertises them) — `fork` / `subagent` / `goal` (need a Claude
  Code host) and `cc-workflows-ultracode` (needs the Workflow tool). The coordinator is a Python script
  that cannot probe the host, so these stay OFF by default; the host enables them explicitly
  (`--host-capable` / `--workflow-available`).

**The degrade ladder (R23):** `cc-workflows-ultracode → team-execution → inline` — the same capability
ladder as `lifecycle_state.ORCHESTRATION_TIERS`. A backend NOT on the ladder (`fork` / `subagent` / `goal`
/ `manual`) has no defined lower rung.

**The presence-conditional degrade decision (R23/AE1).** When a leaf's chosen backend is unavailable,
`degrade_decision` returns one of `dispatch` / `degrade` / `halt`:

| Condition | Decision |
|---|---|
| backend available | **dispatch** on it |
| operator **attending** the leaf | **HALT** + page (the operator decides; never auto-degrade under their nose) |
| **guarantee-bearing** (`guarantee_tags` set or `degrade_policy="halt"`) | **HALT** even when away |
| already **side-effected** (a `destructive` leaf: deploy/migration/write/repo-mutation) | **HALT** — never re-run on a lesser backend (no duplicate side effect) |
| autonomous + away + no guarantee + no side effect | **degrade** to the first available lower rung + record a visible `DegradeReceipt` (surfaced in `/outcome report`) |
| backend not on the ladder, or no lower rung available | **HALT** (no silent substitution, R5) |

The host signals presence to the coordinator via `/outcome advance --autonomous` (away → degrade) vs the
default interactive advance (attending → HALT).

**Liveness (R31).** A dispatched leaf carries optional `heartbeat_seconds` / `timeout_seconds` budgets; a
breach reclaims it as the `stalled` terminal (pages once, cascades to its downstream subtree) so a hung
`cc-workflows` / `/goal` leaf is never waited on forever.

**Frontier-budget + fork-cost levers (R7).** `recommend_outcome_backend` wraps the leaf recommender:
a wide ready frontier downgrades a per-leaf `cc-workflows-ultracode` recommendation to `team-execution`
(a dynamic workflow per leaf is expensive); the `fork` cost lever is claimed only when `fork_is_cheap`
holds (model + system prompt + tools match the parent within the cache TTL — else a fork pays a full
cache miss and is not cheap).

---

## 9. References

- Storage contract (where the choice lives): [`references/saga-spec.md`](./saga-spec.md)
  (`orchestration_mode` / `orchestration_ref`, enum domain §4).
- The work-shape signals, which now select a recorded rationale rather than a backend: [`scripts/lifecycle_state.py`](../scripts/lifecycle_state.py)
  (`should_offer_team_execution`, `recommend_execution_backend`).
- Channel-inline offer convention (do not duplicate): [`skills/brainstorm/SKILL.md`](../skills/brainstorm/SKILL.md).
- Decision record: [`docs/engineering-journal/DECISIONS.md`](../../../docs/engineering-journal/DECISIONS.md)
  `#operator-choice-framework`.
