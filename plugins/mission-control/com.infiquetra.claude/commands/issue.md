---
name: issue
description: Primary SDLC issue creation and prepared handoff command with source artifact support
---

Create or prepare an SDLC issue in any Infiquetra repository. This is the primary user-facing
issue command; `/issue` remains a compatibility alias.

## Usage

```
/issue [type] [--repo repository-name] [--prepare|--draft] [--from artifact] [--maturity value]
```

## Arguments

- `type` — Optional issue type: `capability`, `enhancement`, `defect`, `exploration`, `context-update`, `objective`
- `--repo` — Target repository name without the org prefix
- `--prepare` — Write a reviewable prepared draft and JSON sidecar without mutating GitHub
- `--draft` — Alias for `--prepare`
- `--from` — Source artifact: local path, GitHub issue/PR URL, branch ref, or natural search hint
- `--maturity` — Override inferred handoff maturity: `idea-ready`, `requirements-ready`, `plan-ready`, `resume-ready`, or `deferred-context`

## What This Does

1. Infers or asks for issue type, target repository, target team, and target project.
2. Resolves explicit source artifacts from `--from`.
3. Searches durable repo-local artifacts when natural language implies one, such as "from the brainstorm" or "handoff the plan".
4. Infers handoff maturity from source location unless `--maturity` is provided.
5. Uses `issue prepare` for non-mutating prepared drafts.
6. Uses `issue create-prepared` for confirmed GitHub mutation from a prepared draft.
7. Keeps `/loop` out of recipient guidance; handoff issues may suggest `/plan <issue>` or `/work <issue>`.
8. Lets mission-control compile the prepared issue body from the vendored issue contract; do not copy
   SDLC issue template sections into Saga or handoff prompts.

## Examples

```
/issue --prepare from the brainstorm for Asgard
/issue --draft --from docs/plans/2026-05-30-002-feat-sdlc-handoff-flow-plan.md
/issue capability --repo infiquetra-claude-plugins --from docs/brainstorms/example.md
/issue --prepare --from branch:current --maturity resume-ready
```

## Script Commands

Prepare from a source artifact:

```bash
python3 ~/.claude/plugins/cache/infiquetra-plugins/mission-control/2.1.0/scripts/sdlc_manager.py \
  issue prepare --repo infiquetra-claude-plugins --type capability \
  --team campps --project campps --risk medium \
  --from docs/plans/example.md --maturity plan-ready
```

Create after review and confirmation:

```bash
python3 ~/.claude/plugins/cache/infiquetra-plugins/mission-control/2.1.0/scripts/sdlc_manager.py \
  issue create-prepared docs/sdlc-issue-drafts/<draft>.md
```

## Instructions

When the user invokes `/issue`:

1. If the user says `--prepare`, `--draft`, "prepare", or "draft", route to `issue prepare`.
2. If the user gives `--from <artifact>`, pass it through to `issue prepare --from <artifact>`.
3. If the user says "from the brainstorm", "from the plan", "handoff the plan", or similar natural language, search durable lifecycle artifacts before asking for a path.
4. If multiple artifacts match, ask the user to choose; do not guess.
5. If the user gives `--maturity`, pass it through to `issue prepare --maturity`.
6. If creating from an existing prepared draft, run `issue create-prepared`; show the mutation plan and require confirmation unless the user explicitly requested the confirmed mutation.
7. If target team or project is ambiguous, ask. Do not guess between the active teams (Asgard and CAMPPS).
8. Ensure the prepared issue is self-contained for a recipient without `saga`.
9. If the recipient does have `saga`, suggest `/plan <issue>` for `idea-ready` or `requirements-ready`, and `/work <issue>` for `plan-ready` or `resume-ready`.
10. Do not hand-write actionable issue template bodies in this command; route source text through
    `issue prepare` so the vendored Hermes contract supplies required sections and readiness checks.
