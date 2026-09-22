# Self-edit safety — the tiered gate

The load-bearing safety contract for `/retro`. A meta-improvement engine that edits the journal, the
auto-memory, directives, and the lifecycle SKILLs is powerful and dangerous. The gate keeps it from ever
silently changing anything that already exists.

---

## The tiered gate

> **AUTO-APPLY is ONLY a PURE ADDITIVE APPEND of a NEW journal entry (LEARNINGS / DECISIONS / QUEUED /
> ARCHIVE). ANY delete, modify, or move of existing lines is PROPOSE-DIFF-AND-WAIT.**

### Tier 1 — AUTO (no confirmation)

The single auto-apply case: **appending one new, self-contained entry** to `LEARNINGS.md`,
`DECISIONS.md`, `QUEUED.md`, or `ARCHIVE.md`. The file only grows; nothing existing is touched. This is the
compounding sink — promotion has to be cheap or it does not happen.

### Tier 2 — PROPOSE-DIFF-AND-WAIT (show the diff + `AskUserQuestion` apply / skip / modify; NEVER auto-apply)

Everything that deletes, modifies, or moves existing content, plus everything outside the journal:

| Target | Why Tier 2 |
|---|---|
| An **edit to an existing journal entry** (curation sweep) | modifies existing lines |
| A **`QUEUED → ARCHIVE` move** | *deletes* from `QUEUED.md` (ARCHIVE side is an append, but the QUEUED side is a delete) — **propose, not auto** |
| The **`.claude` auto-memory** (`MEMORY.md` + topic files) | not the journal; high-value, high-risk |
| **Directive files** (repo `CLAUDE.md`, global `~/.claude` directives) | changes how agents behave |
| The **saga SKILLs** — **INCLUDING `skills/retro/SKILL.md`** | self-modification; `/retro` may *propose* a diff to its own skill but **never self-applies** one |

**A move is two operations.** Even when one half is an append, if the other half deletes existing lines the
whole move is Tier 2. The `QUEUED → ARCHIVE` move is the canonical example.

---

## Propose-diff presentation format

For each Tier-2 change, present:

1. **Target** — the file path (repo-relative; the one exception is a global `~/.claude/` path, below).
2. **Why** — the sweep / pass that surfaced it (staleness / contradiction / dedup / rule-enforcement /
   refine-lifecycle / refine-directives / memory-pruning).
3. **The diff** — a real unified diff (`- ` removed lines, `+ ` added lines) so the operator sees exactly
   what changes.
4. **The question** — `AskUserQuestion`: **apply** / **skip** / **modify** (modify lets the operator
   redirect the edit). In a channel session, inline the choices instead (brainstorm convention).

Never apply a Tier-2 change without an explicit **apply**. "Modify" loops back to a revised diff.

---

## In-repo vs global / cross-project directives

Directive surfaces are **NOT one bucket**. Classify before proposing:

### (a) IN-REPO

The repo `CLAUDE.md` and the lifecycle SKILLs. This plugin has **no `agents/` dir** — the convention is
**generic agents** (`Explore` / `Task`), so there is no in-repo agent file to edit. Propose with a normal
diff and a **repo-relative** path. Affects this repo only.

### (b) GLOBAL / CROSS-PROJECT

`~/.claude/CLAUDE.md`, `~/.claude/agents/*.md`, and antigravity directives. These live **OUTSIDE this
repo** and affect **EVERY project**. A global / cross-project proposal MUST carry an explicit warning in
its diff header:

> **WARNING: this changes your GLOBAL Claude config and affects ALL projects, not just this repo.**

The path here is **deliberately absolute** (`~/.claude/...`) — the file genuinely lives outside the repo,
so this is the one place a non-repo-relative path is correct. The warning is non-negotiable: a
cross-project edit that looks like a repo edit is the failure mode this tier exists to prevent.

---

## Never auto-launch

`/retro` **never** auto-launches:

- a **destructive self-edit** — no Tier-2 change applies without the operator's explicit **apply**;
- **starting a big multi-file refactor** — one surfaced by a pass is **OFFERED** and started only on
  the operator's pick. The backend is not part of the offer: `../../../references/operator-choice.md`
  §1 has one value, `inline`, since issue #1030 archived the others.

The engine proposes; the operator disposes. The only thing it does on its own is grow the journal.
