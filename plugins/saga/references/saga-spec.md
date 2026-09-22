# Saga Specification (saga)

**Status:** canonical contract · **schema_version:** `1.0` · **plugin version:** 0.24.0
**Engine:** [`scripts/saga.py`](../scripts/saga.py)

> **Issue 1030 removed `/resume`, `/loop` and `/handoff`.** This file is the storage contract and it
> is current: the fields, their types and their invariants are unchanged. Where it names one of
> those commands as a writer or a consumer, read it as the record of which command wrote a field,
> never as a command to run. `/plan` and `/work` are the writers that remain.

**Audience:** the execution-loop commands (`/plan`, `/work`) implement against this
file when they are rebuilt. They MUST treat the field names, enum values, and operation semantics below as
the single source of truth. If code and this document disagree, that is a bug in one of them — fix it, do
not work around it.

> The engine shipped as a primitive in 0.4.0 (unit tests + manual smoke) and is now **consumed**: `/plan`
> (0.7.0) writes a plan saga via `save`, `/code-review` (0.8.0) is the first review-track consumer
> (append-only/never-mint to an existing thread's `review_paths`), and `/work` (0.10.0) is the **primary
> writer** — it `scan`s/`restore`s on re-entry and writes a tick per phase. The `/resume` and `/loop`
> wiring that was queued here never shipped; issue 1030 removed both commands instead, and `/work`
> owns re-entry. This spec is the single source of truth those consumers implement against.

---

## 1. What a saga is

A **saga** is the durable, resumable work-state envelope for **one thread of lifecycle work** — exactly one
GitHub issue (`kind=issue`) or one ad-hoc task (`kind=task`). It is the spine that carries a single thread
from idea through plan, work, review, QA, and retro across many sessions, machines, and rounds. A saga
answers, from cold, three questions a resumer needs:

1. **Where are we?** — `lifecycle_phase`, `phase`, `phase_status`, `round`.
2. **What is the disposition?** — `status` (active / blocked / paused / handed-off / done / abandoned).
3. **What is the single next move?** — `next_step` (the imperative resume anchor) + `## Remaining`.

A saga is a **log of immutable ticks**. Each save appends a new timestamped envelope file; the
newest-by-filename tick is the current state. Earlier ticks are immutable history. A derived
`state.json` index summarizes all sagas for fast lookup, but it is rebuildable and never authoritative.

### 1.1 Ownership boundary (a saga links, it does not own, another owner's state)

A saga owns **only its own work-thread state**. Everything else it references by pointer. This is a hard
directive boundary:

| Owner | Owns | Saga holds |
|---|---|---|
| **mission-control** | the GitHub issue, its body, labels, project-board fields, comments | `issue_ref` pointer (`owner/repo#N`), cached scalars for offline display only |
| **deploy** | deployment mutation, tag promotion, environment state | `destination` intent + `pr_refs`; never a deploy authority |
| **engineering-journal** (`docs/engineering-journal/`) | the durable DECISIONS / LEARNINGS record | `journal_refs`, `adr_refs` pointers; `## Decisions` mirrors KTDs but the journal is canonical |
| **git** | branch, commit, working tree | `branch`, `head_sha`, `last_commit_sha` cached for offline display only |

A saga is **valid offline** (it reads no network to `restore`) but is **never the authority** for another
owner's state. When a saga's cached scalar (e.g. a stale `branch`) disagrees with the owner, the owner wins.

---

## 2. Identity

A saga's id is **derived** from `kind` + `id`, minted at birth, and **sticky** for the saga's whole life:

```
derive_saga_id("issue", "42")               -> "issue-42"
derive_saga_id("task", "Saga Foundation!")  -> "task-saga-foundation"
```

- `issue-<N>` — `<N>` is the issue number verbatim.
- `task-<slug>` — `<slug>` is `slugify(id)`: lowercase, alphanumeric runs hyphen-joined, empty -> `"saga"`.

**`round` and `phase` are FIELDS, never part of identity.** A saga keeps one directory
(`sagas/<saga_id>/`) across all rounds and phases; round/phase live in the frontmatter. This is the whole
point of the unify: one stable home per thread, many ticks inside it.

### 2.1 Adopted-issue cross-reference (`issue_ref` -> `saga_id`)

A task-born saga that later gets a GitHub issue **keeps its `task-<slug>` id** (the id is sticky) and gains
an `issue_ref` (`owner/repo#N`). Its directory name still says `task-…`, which would make it invisible to a
"find by issue number" lookup. The derived index closes that gap: a reader resolves an issue number to a
`saga_id` by scanning `state.json.sagas[*].issue_ref`, not by guessing the directory name.

> **Consumer rule:** to find the saga for issue N, first try `derive_saga_id("issue", N)`; if that has no
> directory, scan `state.json.sagas` for a `saga_id` whose `issue_ref` ends in `#N`. Do **not** rename the
> directory to match the issue — the id is sticky.

### 2.2 Collision guard (task-slug)

Two different tasks can slugify to the same `task-<slug>` (e.g. "Saga Foundation" and "saga-foundation!").
Before minting a brand-new saga at a `task-<slug>` directory that already exists, a consumer **MUST** check
the existing latest tick:

- **Same thread** (matching `issue_ref` / `created_at`, or the user confirms "resume this") -> reuse it
  (append a tick). This is the common, correct case.
- **Divergent thread** (different `issue_ref` / `created_at` and the user did not confirm resume) -> refuse
  or warn; the consumer should disambiguate the slug (e.g. append a discriminator to `id` before deriving)
  rather than silently fork an unrelated thread onto the same id.

### 2.3 Slug-instability mitigation

A task description that drifts ("Saga foundation" -> "Saga foundation engine") slugs to a different id and
would mint a second saga for the same work. Mitigation is a **consumer convention**, not engine magic:
`/plan` (and any creation path) **SHOULD `scan` first and offer "resume existing saga?"** before minting a
new one. The engine cannot detect intent; the consumer must.

---

## 3. File format

Each tick is a gstack-style envelope: **YAML frontmatter (machine fields) + a Markdown body (prose
sections)**, stored at `sagas/<saga_id>/<YYYYMMDD-HHMMSS>.md`. `render_envelope` / `parse_envelope` are
exact inverses and preserve unknown keys (§3.5).

### 3.1 Frontmatter field table

Rendered in this exact order (`FRONTMATTER_FIELDS`), then sorted `extra` keys. `req` = required to
construct a `Saga` (no default); all others have the listed default.

| Field | Type | Req | Default | Purpose |
|---|---|---|---|---|
| `schema_version` | str | — | `"1.0"` | Envelope schema version (§9). |
| `saga_id` | str | ✅ | — | Sticky derived id (§2). |
| `kind` | str | ✅ | — | `issue` or `task`. |
| `id` | str | ✅ | — | Issue number (as str) or task slug source. |
| `created_at` | str (ISO) | — | `""` | First tick's timestamp; sticky across ticks. |
| `updated_at` | str (ISO) | — | `""` | This tick's timestamp (= save moment). |
| `lifecycle_phase` | enum | — | `ideation` | CE-flow position (§4) — **MUST** be in `LIFECYCLE_PHASES`. |
| `phase_status` | enum | — | `pending` | Phase completion (§4) — **MUST** be in `PHASE_STATUSES`. |
| `status` | enum | — | `active` | Thread disposition (§4) — **MUST** be in `STATUSES`, **MUST NOT** be `pending`/`in_progress`. |
| `next_step` | str | — | `""` | The one imperative resume anchor (top of `## Remaining`). |
| `orchestration_mode` | enum | — | `inline` | How work runs — decision contract in `references/operator-choice.md`; **MUST** be in `ORCHESTRATION_MODES`. |
| `orchestration_ref` | str | — | `""` | The DURABLE pointer into the orchestration: the team name (`team-execution`) or the canonical spec JSON path (`cc-workflows-ultracode`). Never holds a workflow run handle (#693 — that is `orchestration_run_id`). |
| `orchestration_run_id` | str | — | `""` | The TRANSIENT workflow run handle the Workflow tool returns at launch (#693), recorded by `/work` post-launch. Set only for `cc-workflows-ultracode`; empty on older sagas and other backends. |
| `orchestration_recommended` | str | — | `""` | The backend the recommender suggested for this decision (R12). Empty on older sagas. |
| `orchestration_operator_choice` | str | — | `""` | The backend the operator actually picked (R12). Differs from `orchestration_mode` when overriding. Empty on older sagas. |
| `orchestration_downgrade` | str | — | `""` | One-line capability-portable downgrade note (R11). Set on an off-host resume when the Workflow tool is unavailable and the orchestration tier recompiled DOWN (unit specs + per-unit tiers preserved); empty on a host that ran the authored tier. Empty on older sagas. |
| `issue_ref` | str | — | `""` | `owner/repo#N` pointer; empty for plan-only / pre-issue work. |
| `destination` | enum | — | `plan-only` | Routing intent — **MUST** be in `DESTINATIONS`. Mirrors `lifecycle_state`. |
| `deploy_autonomy` | enum | — | `""` | Gate-or-auto posture for the saga→deploy edge (issue #395, KTD3). One of `""`/`gate`/`auto`. Authored once at `/plan` (Phase 5.1, only when `destination=nonprod-deploy`); read — never re-asked — by `deploy_handoff.offer`. Carried forward like `destination`. Empty on older sagas and non-deploy destinations; `deploy_handoff` reads absent/empty as the safe `gate` default (a missing posture can never auto-fire). Mirrored into `state.json.sagas[*]`. |
| `round` | int | — | `0` | Current PR/iteration round. |
| `phase` | int | — | `0` | Current numeric phase within the work plan. |
| `progress_pct` | int | — | `0` | Coarse progress (display only). |
| `plan_path` | str | — | `""` | Pointer to the durable plan doc. |
| `work_session_paths` | list[str] | — | snapshot | Pointers to `docs/work-sessions/` writeups. |
| `review_paths` | list[str] | — | snapshot | Pointers to review docs. |
| `qa_paths` | list[str] | — | snapshot | Pointers to QA docs. |
| `branch` | str | — | `""` | Cached git branch (offline display; git is authority). |
| `head_sha` | str | — | `""` | Cached short HEAD (offline display). |
| `last_commit_sha` | str | — | `""` | Cached full HEAD (offline display). |
| `files_modified` | list[str] | — | snapshot | Files touched this thread (display). |
| `rounds_seen` | list[int] | — | snapshot | Every round number observed; drives `next_round` (§6). |
| `next_round` | int | — | `1` | Derived: `max(rounds_seen)+1` else `1`. Set by `save`, not by caller. |
| `pr_refs` | list[str] | — | snapshot | Pointers to PRs. |
| `adr_refs` | list[str] | — | snapshot | `ADR-NNNN` pointers into the journal. |
| `journal_refs` | list[str] | — | snapshot | Pointers to journal entries. |
| `ceremony_transition` | str | — | `""` | The ship ceremony's last transition run (#345), e.g. `open_pr`. Carry-forward scalar, not a snapshot list — one thread had one ceremony in flight. The ceremony was removed in #1027 and nothing writes this now; #1030 retires it with the commands that read it. |
| `ceremony_tier` | str | — | `""` | The reversibility tier of `ceremony_transition` (`reversible`/`additive`/`always_operator`), #345. No index was stored; the ceremony derived it from the transition name against its own canonical order each read, so there was nothing to drift out of sync. Removed with the ceremony in #1027; #1030 retires it. |
| `blockers` | str | — | `""` | Free-text blockers. |
| `open_questions` | list[str] | — | snapshot | Outstanding questions (snapshot — see §6). |
| `checks_run` | list[str] | — | snapshot | Tests / gates run (snapshot). |
| `source` | str | — | `""` | Origin artifact path (e.g. `docs/plans/…`). |

"snapshot" = list field with full-snapshot semantics (§6); defaults to the `ABSENT` sentinel in memory but
is always a concrete list once persisted/parsed.

**Body sections** (after the closing `---`), all free-form prose, all preserved on round-trip:

| Heading | Saga field | Purpose |
|---|---|---|
| `## Summary` | `summary` | One-paragraph state of the thread. |
| `## Decisions` | `decisions` | KTDs (key technical decisions) — mirrored to the journal, which is canonical. |
| `## Remaining` | `remaining` | Outstanding work; **the top item equals `next_step`**. |
| `## Notes / Tried` | `notes` | Scratchpad / tried-and-rejected notes. The parser also accepts `## Notes`. |

### 3.2 The three stored axes + one derived (MUST rules)

There are **three independent stored axes** and **one derived** value. Keeping them separate removes the
historical `status`↔`phase_status` ambiguity.

- **`lifecycle_phase`** — *where in the CE flow are we.* One of
  `ideation | brainstorm | plan | review | work | qa | retro`. This is a **superset** of
  `handoff_envelope.infer_lifecycle_phase` (which emits only
  `ideation | brainstorm | plan | review | work | unknown`); saga **extends** it (adds `qa`, `retro`; never
  emits `unknown`). It is the flow-position field — "have we ideated and brainstormed yet."
  **MUST** be a member of `LIFECYCLE_PHASES`.
- **`phase_status`** — *is the current numeric `phase` finished.* One of `pending | in_progress | complete`.
  **Authoritative** for "is the phase done." Drives `next_phase` (§5). **MUST** be a member of
  `PHASE_STATUSES`.
- **`status`** — *thread disposition.* One of `active | blocked | paused | handed-off | done | abandoned`.
  **MUST** be a member of `STATUSES`. **MUST NOT** ever take `pending` or `in_progress` — those values
  belong exclusively to `phase_status`. A saga can be `phase_status=complete` while `status=active` (phase
  done, thread still going) or `status=done` (thread finished).
- **`maturity`** — **DERIVED, NEVER STORED in saga-tick frontmatter.** Computed at `/handoff` time
  from `lifecycle_phase` via `PHASE_TO_MATURITY`. No `maturity` key ever appears in saga-tick
  frontmatter; any consumer that needs it derives it. Off-chain artifacts declare their own `maturity`
  in their own frontmatter under their own contract (see §3.3 note).

### 3.3 `lifecycle_phase` -> `maturity` derivation (handoff only)

| `lifecycle_phase` | derived `maturity` |
|---|---|
| `ideation` | `idea-ready` |
| `brainstorm` | `requirements-ready` |
| `plan` | `plan-ready` |
| `review` | `plan-ready` (declared, never written — see below) |
| `work` | `resume-ready` |
| `qa` | `resume-ready` |
| `retro` | `resume-ready` |

Fallback for any unmapped value: `requirements-ready` (matches `handoff_envelope.infer_maturity`'s default).

**`review` is a declared phase that nothing writes.** It is a legal value of `LIFECYCLE_PHASES` in
`scripts/saga.py` and of `--lifecycle-phase`, and a repository-wide search finds no code path that
sets it. Plan review is a step inside the plan phase — `/plan` Phase 5.4 dispatches it and loops on
repair — so a saga goes `plan` → `work` and never records `review`. The row stays because the value
is accepted on read; it is documented as unwritten so a reader does not go looking for the writer.
Whether the phase should become one a step advances is an open operator decision, recorded on issue
934 and not taken here.

**Off-chain doc-path note (`/spec`).** A `docs/specs/` artifact (off-chain `/spec`) is not on the saga
chain: `handoff_envelope.infer_lifecycle_phase` returns `"unknown"` for it (no `spec` member is added to
`LIFECYCLE_PHASES`), and `infer_maturity` maps `docs/specs/` → `requirements-ready` directly (a sharp
WHAT — equals the unmapped fallback, set explicitly for consistency). A spec hands off as
`requirements-ready` with `lifecycle_phase: unknown`.

**Off-chain artifact maturity note.** The derived-never-stored rule above governs saga-tick
frontmatter only. An off-chain artifact (e.g. a Brainstorm requirements doc under
`docs/brainstorms/`) declares its own `maturity` in its own frontmatter under its own section
contract (`plugins/saga/skills/brainstorm/references/requirements-sections.md`);
`pending-confirmation` is a valid artifact maturity meaning the boundary is recorded, unconfirmed,
and carries no durable route. The declared `brainstorm-scope-confirmation` gate (see
`plugins/saga/skills/brainstorm/SKILL.md` Phase 2.5) is the gate that promotes that artifact
maturity from `pending-confirmation` to `requirements-ready`.

### 3.4 Concrete example envelope

`sagas/issue-42/20260602-141233.md`:

```markdown
---
schema_version: "1.0"
saga_id: issue-42
kind: issue
id: "42"
created_at: "2026-06-02T14:05:10+00:00"
updated_at: "2026-06-02T14:12:33+00:00"
lifecycle_phase: work
phase_status: in_progress
status: active
next_step: "wire /resume to call saga.restore"
orchestration_mode: cc-workflows-ultracode
orchestration_ref: "docs/workflows/2026-07-01-evidence-provenance-manifests-spec.json"
orchestration_run_id: "wf_7dbd5245-def"
orchestration_recommended: cc-workflows-ultracode
orchestration_operator_choice: cc-workflows-ultracode
issue_ref: "infiquetra/infiquetra-claude-plugins#42"
destination: pr
round: 2
phase: 3
progress_pct: 60
plan_path: docs/plans/2026-06-02-saga-foundation.md
work_session_paths:
  - docs/work-sessions/2026-06-02-saga-engine.md
review_paths: []
qa_paths: []
branch: feature/saga-foundation
head_sha: a1b2c3d
last_commit_sha: a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0
files_modified:
  - plugins/saga/scripts/saga.py
rounds_seen:
  - 1
  - 2
next_round: 3
pr_refs:
  - infiquetra/infiquetra-claude-plugins#170
adr_refs:
  - ADR-0042
journal_refs:
  - "docs/engineering-journal/DECISIONS.md#saga-foundation"
blockers: ""
open_questions:
  - "GC policy for old ticks?"
checks_run:
  - pytest
  - ruff
source: docs/plans/2026-06-02-saga-foundation.md
---

## Summary

Saga engine built; wrappers + spec done. Mid-wiring of consumers.

## Decisions

Derived sticky id; append-only log + derived index; filename-as-order (never mtime).

## Remaining

wire /resume to call saga.restore
then /work, /loop, /plan

## Notes / Tried

Considered minted UUID ids — rejected (not human-legible, no offline issue lookup).
```

### 3.5 Unknown-key preservation (`extra`)

`parse_envelope` routes any frontmatter key it does not recognize into `Saga.extra`; `render_envelope`
re-emits `extra` keys (sorted) after the known fields. A newer writer's field therefore survives a
read-modify-write by an older reader — forward-compatible round-trip. Consumers **MUST NOT** strip `extra`.

---

## 4. Enum domains (authoritative)

```python
LIFECYCLE_PHASES = ("ideation", "brainstorm", "plan", "review", "work", "qa", "retro")
PHASE_STATUSES = ("pending", "in_progress", "complete")
STATUSES = ("active", "blocked", "paused", "handed-off", "done", "abandoned")
DESTINATIONS = ("plan-only", "pr", "merge", "nonprod-deploy")
ORCHESTRATION_MODES = ("inline", "team-execution", "cc-workflows-ultracode")
HANDOFF_MATURITIES = ("idea-ready", "requirements-ready", "plan-ready", "resume-ready", "deferred-context", "pending-confirmation")
```

`destination` mirrors `lifecycle_state.normalize_destination`'s canonical set — use that helper to normalize
user-facing labels (`deploy` -> `nonprod-deploy`, etc.) before storing. `HANDOFF_MATURITIES` is
implemented in `plugins/saga/scripts/handoff_envelope.py`. Frontmatter `maturity` must be the top-level `maturity:` key of the YAML mapping delimited by `---` lines, decided by parsing that
block as YAML rather than by scanning lines. Any other appearance inside the block — a sequence item
at any column, a key nested under another mapping key, a flow-style mapping nested under another key, or a
`maturity:` line in a block that will not parse — does not declare and fails closed as
`unknown:carrier:`, never falling through to the path rule. A flow-style mapping that is itself the whole top-level mapping declares like any top-level key. An unrecognized non-empty, empty, non-delimited carrier (within the first 30 lines), unterminated block, or unreadable
file (within the first 8192 bytes) fails closed with no durable route and a diagnostic, rather than falling through to the path rule, provided the declaration lies within the bounded read windows; beyond the 8192-byte window the source fails closed as `unknown:unterminated:`.
The field's runtime domain is consequently NOT closed at the six values: `infer_maturity` may also
return the empty string, an `unknown:unrecognized:<raw>` sentinel carrying an unrecognized raw value
(reserved namespace `unrecognized:` that no vocabulary value contains, so author text cannot forge it),
a `unknown:carrier:<raw>` sentinel for a non-delimited carrier (maturity declared outside a delimited
block), a `unknown:unterminated:<raw>` sentinel for a block whose closing delimiter was not found — either genuinely absent, or present but beyond the 8192-byte frontmatter read window (opening `---` without
closing `---`), `unknown:unreadable` for a read/decode failure, or `unknown:out-of-root:<path>` for a source that resolves outside the declared root. A source that resolves outside the declared root is never read: if its path carries a marker directory (`docs/brainstorms/` and the like) and the same subpath exists inside the root, that in-root file is read instead and its declaration decides; otherwise the source is refused with `unknown:out-of-root:`, whatever it declares, whether or not it exists, and however its path is spelled. The envelope's published
`handoff_maturity` field is bounded to 120 characters after the `unknown:` prefix (the helper may
return the full raw value, but the published field is truncated; the `unknown:` prefix plus its
discriminator segment is reserved and never appears in author-declared values), the fail-closed shapes
recorded in `DECISIONS.md`
`{#913-maturity-unknown-sentinel}` and specified for consumers in §4. Consumers MUST route on the
vocabulary values only and stop on the sentinel shapes.

Shaping is an Operations board Status, not a Saga lifecycle phase, not a Saga command, and not an automatic consequence of any Saga capability completing. Mission Control is the only routine writer of that field. Cross-reference `plugins/saga/skills/plan/SKILL.md` §0.6, which already states the same derivation boundary, and note that Office Hours' lowercase "discovery / shaping" phrasing is ordinary English for its own activity, unrelated to the board column (the lifecycle-consistency check pins those exact phrases mechanically).

---

## 5. Storage

### 5.1 Three storage tiers

```
.claude/saga/          # git-ignored (.gitignore) — volatile local state
├── sagas/                             # CANONICAL — append-only immutable envelope log
│   ├── issue-42/
│   │   ├── 20260602-140510.md         # tick 1
│   │   └── 20260602-141233.md         # tick 2 — newest FILENAME = current state
│   └── task-saga-foundation/
│       └── 20260602-093000.md
├── state.json                         # DERIVED index (rebuildable from a scan; never authoritative)
└── checkpoints/                       # LEGACY (pre-0.4.0) — scan reads as low-priority fallback, 1 version
```

- **`sagas/` is canonical.** Each tick is immutable; `save` never overwrites a tick, it appends a new one.
- **`state.json` is derived** (§5.4). If it is missing or corrupt, that is **non-fatal**: `scan` rebuilds
  the picture from `sagas/`, and the next `save` rewrites a valid index.
- **`checkpoints/` is legacy.** Pre-0.4.0 per-phase checkpoint files (`{kind}-{id}[-round-N]-phaseM[-status].md`).
  `scan` reads them as **flagged, low-priority fallback for one version** (§8), then they are dropped.

**Additive caches outside the three tiers (git-common-dir, not `.claude/saga`).** Two performance caches
live under the repo's **git common dir** — `saga-outcomes/<id>/` (the OutcomeOrchestrator store) and
`saga-spores/<session_id>.json` (the compaction spore, #281: the active saga box + frozen DAG frontier
that a `PreCompact` hook freezes and a `SessionStart(source=compact)` hook re-injects after an
auto-compaction so the continuing session re-grounds on structured facts, not the lossy prose summary).
They are deliberately NOT under the worktree-relative `.claude/saga` (§5.2) so they survive across
worktrees, and both are **additive and non-canonical** — the anchor, never the authority; deleting either
loses no canonical state (it is rebuilt from the spec/saga + GitHub). See DECISIONS
`#precompact-spore-two-hook`.

### 5.2 Filename IS the order — never `mtime`

Ticks are ordered **purely by filename string**, never by file modification time. The newest tick for a saga
is `max(files, key=envelope_sort_key)`; `restore` reads exactly that file.

> **Why filename, not mtime:** so that **rsync / backup / snapshot-restore** preserve tick order
> deterministically. A copy tool can rewrite every file's mtime (e.g. all-equal on restore, or reordered),
> which would silently corrupt an mtime-ordered scan. Filename order survives any byte-faithful copy.
>
> **This is NOT about git worktrees.** Git worktrees do not copy git-ignored files at all, so saga state
> created in a worktree lives only in that worktree's ignored `.claude/` and is discarded on cleanup — that
> is expected, volatile dev state. The filename-order win is the rsync/backup case, not the worktree case.

### 5.3 Scan ordering + collision

- Filename pattern: `^(?P<ts>\d{8}-\d{6})(?:-(?P<seq>\d+))?\.md$` (`YYYYMMDD-HHMMSS` + optional `-N`).
- **Same-second collision** -> the writer appends `-1`, `-2`, … . The sort key is
  `envelope_sort_key(name) = (ts, seq)` where the base tick `<ts>.md` is `seq=0` and `<ts>-N.md` is `seq=N`.
  This guarantees the suffixed file sorts **after** its base (a naive string compare would wrongly place
  `<ts>-1.md` before `<ts>.md` because `-` < `.`). Ordering is still derived entirely from the filename.
- `scan` returns **one candidate per saga** (the latest tick of each), `sagas/` candidates **newest-first**
  by `envelope_sort_key`, then legacy checkpoints appended after (so live sagas always rank above legacy).
- Non-matching files and non-directory entries are skipped silently.

### 5.4 `state.json` shape (derived index)

```json
{
  "last_updated": "<iso>",
  "active_saga_id": "<saga_id>",
  "sagas": {
    "<saga_id>": {
      "saga_id", "kind", "id", "lifecycle_phase", "phase_status", "status",
      "phase", "round", "next_phase", "next_round", "destination",
      "issue_ref", "plan_path", "next_step", "updated_at"
    }
  },
  "current_work": {
    "kind", "id", "round", "phase", "phase_status", "destination",
    "plan_path", "work_session_path", "next_steps": ["<next_step>"], "saga_id"
  }
}
```

- `sagas` is a per-saga summary map (one entry per known saga).
- `current_work` mirrors the **most-recently-saved** saga, **carries its `saga_id`**, and keeps the legacy
  key set (`plan_path`, `work_session_path`, `next_steps`) **UNCHANGED** — `handoff_envelope.py` and its
  test read `current_work.plan_path` / `current_work.work_session_path`, so those keys MUST stay stable.
  `work_session_path` = the first entry of `work_session_paths` (or `""`).

---

## 6. List merge semantics — full snapshot, never union

A tick is a **full snapshot**, so list fields use snapshot-replace semantics at `save` time. There are
three distinguishable input states (the `ABSENT` sentinel distinguishes "carry forward" from "clear"):

| Incoming list value | Result in the new tick |
|---|---|
| **Populated** `[a, b]` | **REPLACE** — the new tick's list is exactly `[a, b]` (prior list discarded). |
| **Empty** `[]` | **CLEAR** — the new tick's list is `[]`. |
| **`ABSENT`** (omitted) | **CARRY FORWARD** — copy the prior tick's list verbatim (or `[]` for a new saga). |

**Never union.** Union-only lists accumulate stale `open_questions` and `files_modified` that mislead a cold
resume; snapshot semantics let a resume payload **shrink** (e.g. an `open_question` that got answered drops
off the next tick). A persisted/parsed tick always holds **concrete** lists (never `ABSENT`).

**Scalar carry-forward:** a scalar field left at its dataclass default in the incoming saga inherits the
prior tick's value. To *clear* a scalar you must pass a non-default sentinel value explicitly (e.g. `" "`),
since the default and "unset" are indistinguishable for scalars. `created_at` is sticky from the first tick;
`updated_at` is always the save moment; `next_round` is recomputed (§6.1).

### 6.1 Derived-at-save fields

- `next_round = max(rounds_seen) + 1` (or `1` if `rounds_seen` is empty). The caller MUST NOT set it.
- `next_phase = phase + 1 if phase_status == "complete" else phase`. Returned by `save`, surfaced in
  `scan` candidates and `state.json` summaries.
- `branch` / `head_sha` / `last_commit_sha` — if left empty, `save` fills them from a **guarded** git probe
  (`current_git_state`); any git failure yields empty strings (never raises). `restore` never probes git.

---

## 7. Operation contract (`save` / `restore` / `scan`)

| Op | Reads | Writes | Subprocess? | Notes |
|---|---|---|---|---|
| `save(root, saga, *, now=, runner=)` | latest prior tick (`restore`) | new immutable tick + `state.json` | yes (guarded git) | merges (§6); returns `{saga_id, envelope_path, state_path, phase, status, next_phase, next_round}`. |
| `restore(root, saga_id)` | latest tick by filename | — | **no** | cold, branch-agnostic; `None` if no tick. NEVER calls git/subprocess. |
| `scan(root, *, max_candidates=)` | latest tick per saga + legacy | — | no | one candidate/saga, newest-first, legacy appended + flagged. |
| `update_index(root, saga, *, now=)` | existing `state.json` | `state.json` | no | atomic temp+rename; corrupt prior index rebuilt. |
| `latest_envelope_for(root, saga_id)` | tick filenames | — | no | the newest tick `Path` by `envelope_sort_key`, or `None`. |
| `aggregate_context(root, owner, repo, issue, *, runner=)` | saga + `gh` PRs + journal | — | yes (guarded `gh`) | missing `gh` no-raises -> empty PR list. |

### 7.1 Atomicity + best-effort index

`update_index` writes via **temp file + `os.replace`** (atomic on POSIX), so a reader never sees a
half-written `state.json`. The index is nonetheless **best-effort / racy** under concurrent writers: two
sessions saving different sagas can clobber each other's `current_work` (last writer wins). That is
acceptable because:

- `current_work` is rebuildable (re-save the saga, or read it from `sagas/` directly), and
- `scan` (reading `sagas/`) — not `state.json` — is the **source of truth** for "what work exists."

A reader that needs the authoritative current state of saga X MUST `restore(root, X)` (read the canonical
log), not trust `state.json.current_work`.

### 7.2 Cold-resume / branch-agnostic

`restore` reads only the envelope (frontmatter + body). It does **not** consult git, the network, or the
current checkout, so a saga restores **identically on any branch or machine** that has the `sagas/`
directory. (The cached `branch`/`head_sha` may be stale — that is fine, git is the authority for those.)

---

## 8. Migration (pre-0.4.0 -> 0.4.0)

- **Format change:** checkpoints moved from flat `checkpoints/{kind}-{id}[-round-N]-phaseM[-status].md`
  (overwrite-in-place, mtime-ordered) to `sagas/<saga_id>/<YYYYMMDD-HHMMSS>.md` (append-only,
  filename-ordered).
- **No automatic data migration.** Old `checkpoints/` files are **read by `scan` as flagged, low-priority
  fallback for one version** (each carries `legacy: true` and a reduced key set), then support is dropped.
- **Upgrade warning:** complete any in-flight loop on the legacy format **before** upgrading. A loop that
  spans the upgrade should re-save through `saga.save` to materialize a `sagas/` entry; otherwise its state
  lives only in `checkpoints/` and survives just one more version of `scan`.

---

## 9. Versioning

- **`schema_version`** (currently `"1.0"`) is a frontmatter field stamped on every tick. Bump it on any
  breaking change to field meaning or layout. Readers SHOULD tolerate a higher `schema_version` they do not
  fully understand by relying on `extra` round-trip (§3.5) rather than dropping unknown keys.
- **Additive evolution** (new optional frontmatter field) does **not** require a `schema_version` bump: the
  `extra` mechanism preserves it across older readers, and adding a field with a default keeps old envelopes
  parseable.
- The plugin's own SemVer (`plugin.json` / `marketplace.json`) tracks the capability; `schema_version`
  tracks the on-disk envelope contract. They move independently.
- The handoff envelope built by `handoff_envelope.py` carries its own `schema_version` (currently `"1.1"`) under the same rule: bump it on any breaking change to a field's meaning or layout, even when the JSON type is stable. (1.0 → 1.1 is the precedent: `suggested_command` changed from a field that always holds a runnable slash command to one that can hold a non-routable prose diagnostic when `handoff_maturity` is `pending-confirmation` or unrecognized — consumers must branch on `handoff_maturity` before trusting `suggested_command`.)
- **Handoff-maturity field contract (part of the envelope surface).** `handoff_maturity` holds one of
  the six `HANDOFF_MATURITIES` values (§4), the empty string (frontmatter declared the key but left it
  blank), an `unknown:unrecognized:<raw>` sentinel for an unrecognized value (reserved namespace
  `unrecognized:`), a `unknown:carrier:<raw>` sentinel for a non-delimited carrier (maturity declared
  outside a delimited `---` block), a `unknown:unterminated:<raw>` sentinel for a block whose closing delimiter was not found — either genuinely absent, or present but beyond the 8192-byte frontmatter read window (opening `---` without closing `---`), `unknown:unreadable` for a read/decode failure, or `unknown:out-of-root:<path>` for a source that resolves outside the declared root (all
  bounded to 120 characters after the `unknown:` prefix; the `unknown:` prefix and its discriminator
  segment are reserved and never appear in author-declared values; design record: `DECISIONS.md`
  `{#913-maturity-unknown-sentinel}`). For all non-vocabulary shapes `suggested_command` is
  non-routable prose; the process still exits zero, so a consumer typed against the closed vocabulary
  MUST detect the sentinel shapes by prefix/value, not by exit code. Routing `suggested_command` while
  the value is empty, `unknown:`-prefixed, or `pending-confirmation` is an error — stop and fix the
  declaring artifact's frontmatter instead.

---

## 10. Link-vs-duplicate policy

| Concept | Authority (owner) | Saga stores | Why |
|---|---|---|---|
| Issue body / labels / board | mission-control | `issue_ref` pointer | mission-control owns issue artifacts. |
| Plan document | the plan doc | `plan_path` pointer | doc is canonical; saga points. |
| Work-session / review / QA writeups | the docs | `work_session_paths` / `review_paths` / `qa_paths` | docs are canonical. |
| PRs | GitHub | `pr_refs` pointers | GitHub is canonical. |
| Decisions / ADRs / learnings | engineering-journal | `journal_refs` / `adr_refs` + `## Decisions` mirror | journal is canonical; `## Decisions` is a convenience mirror only. |
| Branch / commit | git | `branch` / `head_sha` / `last_commit_sha` cache | git is canonical; cache is for offline display. |
| Deployment | deploy | `destination` intent + `pr_refs` | deploy owns mutation. |

**Rule:** cache tiny scalars for offline display, but **never** treat a cached value as authoritative when
the owner is reachable. When in doubt, store a pointer, not a copy.

---

## 11. Consumer contract (rebuild targets)

Each command below implements against this spec when rebuilt. None call the engine after the 0.4.0 PR —
this table is the wiring contract for their own queued items.

| Command | Reads | Writes (`save`) |
|---|---|---|
| **/plan** | `scan` (§2.3) | `lifecycle_phase=plan`, `phase_status=complete`, `plan_path`, `destination`, `deploy_autonomy` (only when `destination=nonprod-deploy`), `adr_refs`, `decisions`, `orchestration_mode`, `orchestration_recommended`, `orchestration_operator_choice` (derived from an explicit mode flag unless an explicit choice is supplied; omitting both preserves the prior choice or starts empty). |
| **/work** | `restore` (rehydrate `round`/`phase`/`checks_run`/`next_step`) | primary writer: per-phase ticks, round bump (`rounds_seen`), `checks_run`, `work_session_paths`, `issue_ref` adoption, `status=done` at completion. |
| **/code-review** | the diff + `scan`/`restore` (the existing work-thread) | review-track consumer: appends `review_paths` (append-only, never mints); **never advances `lifecycle_phase`** (preserves it). |
| **/qa** | `restore` (the work-thread) | qa-track consumer: writes `qa_paths`; on PASS advances `lifecycle_phase` `work`→`qa`; on FAIL keeps `lifecycle_phase=work`. Never mints. |
| **/resume** | `restore` (cold reconstruction) + `scan` (candidate list) | routes to `/work` or `/handoff`; may save a `status=paused`/`active` re-entry tick. |
| **/loop** | `scan` at start (offer resume) | creation tick + a tick per routing decision; `status=handed-off` when routing to `/handoff`. |

The `/plan` row is rendered from `plugins/saga/references/plan-save-contract.yaml` by
`python3 plugins/saga/scripts/plan_save_contract.py render --write`.
`tests/test_saga_spec_consumer_row.py::test_saga_spec_plan_consumer_row_matches_contract`
fails when they differ. Do not hand-edit the `/plan` row. See the
[maintainer runbook](plan-save-contract.md) for editing, checks, and recovery.

`/handoff` derives `maturity` from `lifecycle_phase` (§3.3) at handoff time; it does not read a stored
`maturity` because there isn't one.

---

## 12. Edge cases (MUST / SHOULD)

- **MUST** keep `status` out of the `phase_status` domain (no `pending`/`in_progress` in `status`) and vice
  versa.
- **MUST** treat a missing/corrupt `state.json` as non-fatal: `scan` rebuilds from `sagas/`.
- **MUST** order ticks by filename (`envelope_sort_key`), never by `mtime` (§5.2).
- **MUST** preserve unknown frontmatter keys via `extra` (§3.5) — never strip them on round-trip.
- **MUST NOT** let `restore` shell out to git or the network (cold, branch-agnostic — §7.2).
- **MUST** treat a missing `gh` as empty PR data in `aggregate_context`/`prior_prs`, never an exception (§7).
- **SHOULD** `scan` and offer "resume existing?" before minting a new task saga (slug-instability — §2.3).
- **SHOULD** guard task-slug collisions against an existing divergent saga before appending (§2.2).
- **SHOULD** resolve issue->saga via `state.json.sagas[*].issue_ref` when the `issue-<N>` directory is
  absent (adopted-issue case — §2.1).

### 12.1 Append-only growth (deferred)

Ticks accumulate; there is **no GC today**. A future `max_ticks` retention policy is the planned seam — it
prunes oldest ticks while keeping the newest authoritative, so it is purely additive and needs **no schema
change**. Until then, growth is bounded only by save frequency and is acceptable for the volatile,
machine-local `.claude/` location.

---

## 13. Provenance manifests (`saga.manifest.v1`)

A provenance manifest is a typed, persisted evidence record for one delegated execution — never a
verdict (schema holds no verdict field; advisory only, R20). Producers write it; gates and reporting
skills consume it. Full contract, requirements (R1-R21), and rejected alternatives: `#285`,
`docs/plans/2026-07-01-evidence-provenance-manifests-plan.md`.

### 13.1 Carrier

One JSON file per execution at `<git-common-dir>/saga-manifests/<saga-id>/<execution-id>.json`
(`../scripts/manifest_store.py`), resolved through the same `resolve_common_dir()` `outcome_store.py`
uses — cross-worktree and cross-session (R19), unlike git-ignored per-checkout ticks. Outcome leaves
additionally carry a typed `manifest_ref` pointer in `CompletionEvent.payload["manifest_ref"]`.

### 13.2 Schema (`../scripts/provenance_manifest.py`)

```
Manifest
├── execution_id, saga_ref, schema ("saga.manifest.v1")
├── attribution: Attribution {kind, identity, effort, protocol}
├── disposition: Disposition, disposition_note, tripwire_note (optional)
├── created_at
├── output_completeness: OutputCompleteness | None
│   {declared_keys, target_count, produced_keys, produced_count, missing_keys}
└── claim_provenance: ClaimProvenance | None
    {claims: [Claim {text, claimed, source_ref, source_revision, adjudicated,
                      mismatch_reason, adjudication: Adjudication | None
                      {adjudicator, sources_read, scope, revision, decision}}]}
```

A *lightweight* manifest carries the envelope with both subrecords `None` (attribution + disposition
+ existence bit only, R9); a *full* manifest adds one or both subrecords. `validate()` enforces the
subrecord is present wherever a gate or contract-bearing unit needs it.

### 13.3 Producer / consumer matrix (R17)

Every schema field below names its producer(s) and every live-or-scheduled reader. No field may
appear here without a reader (guard: `tests/test_manifest_consumer_matrix.py`), and no field named
here may be absent from the `provenance_manifest.py` dataclasses (drift, both directions).

| Field | Producer | Reader | Status |
|---|---|---|---|
| `execution_id` | `manifest_store.py`, `engine_dispatch.py` | `manifest_store.py` (read/list) | live |
| `saga_ref` | `engine_dispatch.py`, `manifest_store.py` | `manifest_store.py` (path resolution) | live |
| `schema` | `provenance_manifest.py` (`Manifest` default) | `manifest_store.py` (version check on read) | live |
| `attribution.kind` | `engine_dispatch.py` (`external-engine`), `manifest_store.py` (`cc-workflows`), team-execution worker exit (`worker-manifest.md`) | `manifest_reader.py` (disposition/attribution tallies) | live (cc-workflows/engine); scheduled (team-execution-worker producer path, R2) |
| `attribution.identity` | `engine_dispatch.py`, `manifest_store.py` | `manifest_reader.py` | live |
| `attribution.effort` | `engine_dispatch.py`, `manifest_store.py` | `manifest_reader.py` | live |
| `attribution.protocol` | `engine_dispatch.py` | `manifest_reader.py` | live |
| `attribution.sandbox` | `engine_dispatch.py` (`build_dispatch_manifest`, #287 R7 pre-hoc scope) | operator/audit prose (declared-vs-actual scope review); `external-engine-workers.md` attribution note | live (optional, absent-tolerant — no `saga.manifest.v1` bump) |
| `disposition` | `engine_dispatch.py`, `manifest_store.py` | `manifest_reader.py` (R18 disposition rate) | live |
| `disposition_note` | `engine_dispatch.py` | operator/skill prose (`/work` SKILL.md post-run step) | live |
| `tripwire_note` | `engine_dispatch.py` (`build_dispatch_manifest`) | `engine_dispatch.py` (`adjudicate_manifest` preservation), operator/audit prose | live (optional, bounded operational note) |
| `created_at` | `engine_dispatch.py`, `manifest_store.py` | `manifest_store.py` (ordering on list) | live |
| `output_completeness` | `manifest_store.py` `record-completeness` (U4/KTD7, driver-materialized) | `completeness_gate.py` semantics via `/work` post-run persistence step (R13); `manifest_reader.py` | live |
| `output_completeness.declared_keys` | `manifest_store.py` (from `Contract.from_unit`) | `/work` SKILL.md post-run step (missing-output trip, R10) | live |
| `output_completeness.target_count` | `manifest_store.py`, `completeness_gate.py` (`Contract`) | `manifest_store.py` (`record-completeness` diff) | live |
| `output_completeness.produced_keys` | `manifest_store.py` (`record-completeness`) | `/work` SKILL.md post-run step | live |
| `output_completeness.produced_count` | `manifest_store.py` (`record-completeness`) | `/work` SKILL.md post-run step | live |
| `output_completeness.missing_keys` | `manifest_store.py` (`record-completeness`) | `/work` SKILL.md post-run step (missing-output trip, R10) | live |
| `economics` | `engine_dispatch.py` (`build_dispatch_manifest`, net-savings copy from dispatch provenance) | `manifest_reader.py`, `/work` and `/code-review` evidence summaries (offload net-savings audit) | live |
| `bridge_run_key` | `engine_dispatch.py` (`build_dispatch_manifest`, stable key from `bridge_receipt.run_id` or receipt hash fallback) | `engine_dispatch.py` / `run_ledger.py` (bridge fact de-duplication and liveness join audit) | live |
| `claim_provenance` / `claims` | `engine_dispatch.py` (claimed-layer at dispatch; adjudicated layer written by Claude via a `manifest_store` update helper, D5) | `manifest_reader.py` (parroting count, verified ratio); `code-review/SKILL.md` B.0 (skip re-verify) | live |
| `claims[].text` | `engine_dispatch.py` | `manifest_reader.py` | live |
| `claims[].claimed` | `engine_dispatch.py` | `manifest_reader.py`, gate adjudication ranking (KTD4) | live |
| `claims[].source_ref` | `engine_dispatch.py` | `code-review/SKILL.md` B.0 | live |
| `claims[].source_revision` | `engine_dispatch.py` | `code-review/SKILL.md` B.0 | live |
| `claims[].adjudicated` | `engine_dispatch.py` (Claude adjudication write path) | `manifest_reader.py` (R16 ratio), `engine_dispatch.satisfy_gate()` (R11) | live |
| `claims[].mismatch_reason` | `provenance_manifest.py` (`mismatch_reason_for`), `engine_dispatch.py` | `manifest_reader.py` (parroting count, R7) | live |
| `claims[].adjudication` | `engine_dispatch.py` | `manifest_reader.py`, `code-review/SKILL.md` B.0 (attested-adjudication check) | live |
| `claims[].adjudication.adjudicator` | `engine_dispatch.py` | `code-review/SKILL.md` B.0 | live |
| `claims[].adjudication.sources_read` | `engine_dispatch.py` | `code-review/SKILL.md` B.0 | live |
| `claims[].adjudication.scope` | `engine_dispatch.py` | `code-review/SKILL.md` B.0 | live |
| `claims[].adjudication.revision` | `engine_dispatch.py` | `code-review/SKILL.md` B.0 | live |
| `claims[].adjudication.decision` | `engine_dispatch.py` | `manifest_reader.py`, `retro/SKILL.md` Phase 1.8 | live |

The one honestly-scheduled leg is `attribution.kind == team-execution` as a *producer* of the
`claim_provenance` subrecord for **external-engine workers running inside team-execution** — it waits
on `#283`'s deferred U12 external-worker wrapper contract (R14). Claude team-execution workers already
emit manifests today per `worker-manifest.md`; only the external-engine-via-team-execution leg is
scheduled, not the field itself.

---

### 13.6 Proof-integrity bridge fields (#388)

`Disposition.PROOF_INTEGRITY` is the manifest disposition for a schema-valid bridge receipt whose
stronger proof contract fails: missing output attestation, empty required output, hash mismatch,
zero external tokens, or producer/consumer liveness contradiction. It is distinct from `UNPROVEN`
(no schema-valid base receipt) and from `DELEGATION_INTEGRITY` (engine self-report contradicts the
independent observer signal).

`Manifest.bridge_run_key` is optional and additive in `saga.manifest.v1`. When present it carries the
stable bridge run key from `bridge_receipt.run_id` or a canonical receipt hash fallback. Consumers use
it to join producer launch evidence to manifest consumption and to de-duplicate run-ledger token facts.

---

## 14. Plan-document contract (distinct from the tick envelope)

The plan document under `docs/plans/` is a separate artifact from the saga tick envelope of section 3,
with its own contract and its own consumers. Nothing in this section belongs in the envelope field
table (§3.1), and no tick field is a plan-doc field — the two schemas never merge.

**Frontmatter.** Every plan carries YAML frontmatter; the required-field set and the field-by-field
contract live in `../skills/plan/references/plan-sections.md` (Plan-doc frontmatter contract), pinned
by `tests/test_plan_artifact_conformance.py`. `backend` takes a value from `ORCHESTRATION_MODES`
(section 4), as narrowed by #808 — `inline` or `team-execution` are the defaults,
`cc-workflows-ultracode` only after explicit invocation. `origin` MUST be emitted whenever an
upstream artifact exists and may be omitted on a cold start; `deepened` is optional.

**Legacy rule.** Legacy is the absence of `backend`, and nothing else. A document without the field is
legacy, reported, and non-failing; a document with it is new-contract and is held to the full
frontmatter and marker contract. There is no bulk rewrite of the legacy corpus — `/work` honours the
field when present and offers only when it is absent.

**Marker triple.** The body MUST use the exact section markers `Implementation Units`,
`Key Technical Decisions`, and the `U1` U-ID prefix; `/doc-review` parses these to recognize the
document as a plan. The definition is pinned by `tests/test_plan_artifact_conformance.py`.

**Consumers.** Saga Work reads `backend`; Document Review recognizes the document by the marker
triple; `/loop` routes on the saga tick, which stays in the envelope of section 3.

**Conformance.** One recursive pass over `docs/plans/` evaluates the declared frontmatter fields and
the marker triple together — shipped as `../scripts/plan_artifact_conformance.py` (runnable; pinned
by `tests/test_plan_artifact_conformance.py`) — so a document cannot satisfy one contract and
silently fail the other. Legacy findings are reported without failing the run.

---

## 15. Plan pre-answer carrier (`plan_pre_answers.v1`)

A caller that has already settled a decision may hand it to `/plan` rather than letting the
conversation re-ask it. The carrier is **intake, not a phase** (KTD4): it is evaluated once, before
the conversation begins, and its only visible effects are the narration of an applied value together
with its caller, and the absence of a question that would otherwise have been asked.

**Transport.** A fenced JSON block inside the `/plan` invocation text — the same seam callers
already write prose into. No file, no CLI flag, no daemon, no state.

**Shape.**

```json
{
  "schema": "plan_pre_answers.v1",
  "caller": "orchestrate",
  "backend": "inline",
  "destination": "plan-only"
}
```

- `schema` — the version token `plan_pre_answers.v1`. Two cases, stated as the code performs them:
  a non-v1 token INSIDE the `plan_pre_answers` family (case-insensitive, token boundary) is refused
  whole — no field from that carrier is applied; a FOREIGN schema family is not a carrier at all and
  is ignored.
- `backend` — decision field, from `inline | team-execution | cc-workflows-ultracode`
  (`ORCHESTRATION_MODES`, section 4). Optional. Operator ruling (review F03, stricter than #808):
  the carrier applies ONLY `inline` automatically, recorded in the plan-doc `backend:` field
  without re-offering; `team-execution` and `cc-workflows-ultracode` are legal plan values but
  require explicit operator invocation, so the carrier stops and surfaces instead of applying.
- `destination` — decision field, from `plan-only | pr | merge | nonprod-deploy` (`DESTINATIONS`,
  section 4). Optional; applied as Phase 5.1's answer and the tick's `--destination` without
  re-asking.
- `caller` — envelope metadata naming the supplying capability for the narration. NOT a decision
  field: exactly two decision fields are admitted (`backend`, `destination`), and anything beyond
  them is rejected rather than ignored. Both decision fields omitted is a valid empty carrier.

**Carrier discipline.** The fence info string must be exactly `json`; at most one carrier is
admitted — a second carrier stops the run rather than letting the first win silently; duplicate JSON
keys stop the run rather than applying the last value; and a `json` block that fails to parse or
repeats a key is a malformed carrier — a stop — only when it is carrier-shaped (its raw text names
the `plan_pre_answers` family). An unrelated malformed JSON example is ignored, exactly as a foreign
schema is, so invocation text that carries no carrier stops nothing (cycle-2 C03/P02/S01).

**Evaluation rules** (validator: `../scripts/plan_pre_answers.py` — runnable; reads the text it is
given, writes nothing, reads no file; pass `--established FIELD=VALUE`, repeatable, for each
decision already established in the thread, so rule 3's contradiction check can run — cycle-2
C04/U04):

1. A valid supplied value — an `inline` backend, or any valid `destination` — is applied and
   visibly narrated together with its `caller`.
2. A missing carrier, or a carrier omitting a field, follows the normal adaptive conversation;
   absence is not an error.
3. An invalid value, or one contradicting an already-established value, stops and surfaces the
   conflict; it never becomes a silent default and never prefers either side.
4. A non-v1 token inside the family is refused whole; a foreign family is ignored (two cases, as
   above).
5. A malformed carrier — a carrier-shaped `json` block that fails to parse or repeats a
   key, or a second carrier — stops the run; an unrelated malformed JSON example is
   ignored.

Direct `/plan` — an issue, a prompt, or a Brainstorm document, no carrier — applies nothing,
narrates nothing, and stops nothing. The carrier is never rendered as a questionnaire, checklist, or
fixed sequence; Phase 0.7 of `../skills/plan/SKILL.md` carries the skill-side intake prose.

## 16. References

- Engine: [`../scripts/saga.py`](../scripts/saga.py)
- Wrappers (delegate to the engine): `../scripts/scaffold_checkpoint.py`,
  `../scripts/find_inflight_work.py`, `../scripts/load_saga_context.py`
- Handoff maturity/phase inference (the source this spec extends):
  `../scripts/handoff_envelope.py` (`infer_maturity`, `infer_lifecycle_phase`)
- Destination normalization: `../scripts/lifecycle_state.py` (`normalize_destination`)
- Design rationale (rejected alternatives, revisit conditions):
  `../../../docs/engineering-journal/DECISIONS.md` (saga-foundation ADR)
- Provenance manifests: `../scripts/provenance_manifest.py`, `../scripts/manifest_store.py`,
  `../scripts/manifest_reader.py`, `#285`,
  `../../../docs/plans/2026-07-01-evidence-provenance-manifests-plan.md`
