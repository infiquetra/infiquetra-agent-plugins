---
name: retro
description: The Infiquetra lifecycle meta-improvement engine — the terminal, advisory phase that turns finished work into durable journal knowledge and gated proposals to improve the lifecycle itself
argument-hint: "[saga-id | issue | branch | time-window] [interview|curate|prune|metrics]"
---

Load `saga/skills/retro/SKILL.md` and run it as the **meta-improvement engine**.

Single command. An optional **pass arg** scopes the run to one pass — `interview` | `curate` | `prune` |
`metrics`; absent, run the full Phase 0-6 procedure.

**The tiered self-edit gate (non-negotiable):** AUTO-APPLY is ONLY a pure additive append of a NEW journal
entry (LEARNINGS / DECISIONS / QUEUED / ARCHIVE); ANY delete / modify / move of existing lines — curation,
the `.claude` auto-memory, directive files, the lifecycle SKILLs (including retro's own SKILL) — is
propose-diff-and-wait (show the diff, ask apply / skip / modify). A global / cross-project directive edit
carries the cross-project warning. See `skills/retro/references/self-edit-safety.md`.

**Boundary:** READ-ONLY on the world (`gh` / `git` read-only, never mutates issues / PRs / the board —
mission-control owns the SDLC); never writes the saga (terminal, saga read-only); never auto-launches an
execution backend or a destructive self-edit; never blocks the chain it follows.

Arguments provided to the command:

`$ARGUMENTS`
