---
date: 2026-08-25
kind: doc-review
target: docs/brainstorms/2026-08-25-voice-plugin-requirements.md
reviewed_revision: c90de14b12e7c77a41ab284ac7f295fecf289772
branch: orch/voice-plugin-ideation
classification: requirements
blocked: false
run_type: post-integration freshness review (affected areas only)
prior_accepted_artifact: docs/reviews/2026-08-25-voice-plugin-requirements-doc-review.md
prior_accepted_revision: a8fa3b94df5131fe4b0c25c8d2f84485d9ae646b
---

# Post-Integration Freshness Review — Voice Plugin Requirements

**Verdict: READY. One validated finding (P2) — the five journal line anchors displaced again by the merge under review — repaired in place; every other evidence anchor verified clean.**

## Review result

| field | value |
|-------|-------|
| target | `docs/brainstorms/2026-08-25-voice-plugin-requirements.md` |
| reviewed revision | `c90de14b12e7c77a41ab284ac7f295fecf289772` |
| branch | `orch/voice-plugin-ideation` |
| classification | requirements (path tie-breaker: `docs/brainstorms/`) |
| run type | post-integration freshness review — affected areas only; not a re-review |
| prior accepted review | `docs/reviews/2026-08-25-voice-plugin-requirements-doc-review.md` at revision `a8fa3b94df5131fe4b0c25c8d2f84485d9ae646b` — preserved untouched |
| blocked | false — no P0/P1 findings |
| artifact | `docs/reviews/2026-08-25-voice-plugin-requirements-post-integration-freshness-review.md` |
| override rationale | none needed |
| linked issue / plan / work-session | none — this run is scoped to evidence-anchor freshness and repair only |

## Why this run exists

Merge `c90de14` integrates `origin/main` at `34a9fcd` (PR #25, the mission-control migration retrospective) into this branch. That change inserted new journal entries into `docs/engineering-journal/DECISIONS.md` and `docs/engineering-journal/LEARNINGS.md` immediately below the `## 2026-08-25` heading — near the TOP of each file, not appended at the end — displacing every line number below by +42 (DECISIONS.md) and +24 (LEARNINGS.md). The accepted review had already repaired these same five anchors once for the same class of drift (its D1), so every line-number anchor in the requirements document was treated as stale until proven otherwise.

## Applied fixes

| finding | edit made to the target document |
|---------|----------------------------------|
| D12 | Five journal anchors rewritten to their verified post-merge locations (old → new table below); no other text touched |

## Readiness summary

The document can still safely drive planning. The merge invalidated exactly the evidence anchors the accepted review predicted would drift, and nothing else: all five journal citations were re-verified entry-by-entry at their new line numbers, and every non-journal citation was proven to still resolve to the content the document claims.

No design decision, requirement, acceptance example, or rubric conclusion was re-litigated. The accepted review's artifact remains the durable record of the full review and was not modified.

## Findings

Finding numbering continues the accepted artifact's D-series; dispositions and priorities follow that artifact's classification of the same defect class.

| id | priority | anchor (at reviewed revision `c90de14`) | validation verdict | disposition | summary |
|----|:--------:|------------------------------------------|--------------------|-------------|---------|
| D12 | P2 | Sources and Research — five journal line citations | valid — merge `c90de14` inserted +42 lines at DECISIONS.md line ~4 and +24 lines at LEARNINGS.md line ~4 (single hunk each, confirmed via `git diff a8fa3b9 c90de14`); the stale anchors land inside unrelated entries, and each true entry was located and content-verified at its displaced position | repaired | Five journal anchors displaced a second time by the retrospective merge |

### D12 anchor-by-anchor evidence

Each repair records the old anchor, the new anchor, and the heading and text confirming the new anchor is right. Entries are newest-first in these journals, so the retrospective entries landed above all cited entries and shifted them by a constant delta.

| old anchor | new anchor | confirmed entry at new anchor |
|------------|------------|-------------------------------|
| `DECISIONS.md:748` | `DECISIONS.md:790` | heading `### A client's real executable is supplied by the operator, never discovered` verified at line 790; old line 748 now sits inside the unrelated `A mutation proof excludes its own binding test` entry |
| `LEARNINGS.md:468` | `LEARNINGS.md:492` | heading `### An optional safety setting is a safety setting that is off` verified at line 492; generalizable rule at line 515 reads "A setting whose empty value disables a control must never be optional, and 'absent' must never mean 'empty'" — the exact claim the citation carries |
| `DECISIONS.md:817` | `DECISIONS.md:859` | heading `### The port descriptor is closed, and its safety fields are stated rather than defaulted` verified at line 859; its `assessment.declared_none` mechanism is the decision counterpart of the LEARNINGS rule the citation pairs it with |
| `LEARNINGS.md:571` | `LEARNINGS.md:595` | heading `### A harness that inherits stdin behaves differently in a terminal than under a scheduler` verified at line 595; generalizable rule reads "A subprocess a program starts on its own initiative should never inherit the parent's standard input … and give it a deadline regardless" — the rule R32 carries |
| `LEARNINGS.md:187` | `LEARNINGS.md:211` | heading `### The cleanup reported containment for a boundary the client can step outside` verified at line 211; generalizable rule reads "State what the mechanism established, not what it was for" — the exact claim the citation carries |

Arithmetic check: every cited line lies below the single insertion hunk in each file, so the displacement is exactly +42 (748→790, 817→859) and +24 (468→492, 571→595, 187→211), matching the `git diff` hunk sizes with no residual.

## Evidence anchors verified clean

Every external anchor the document cites was checked one at a time against the reviewed revision, including those the merge could not have moved.

| anchor | result |
|--------|--------|
| `AGENTS.md:52-53` | clean — lines 52-53 read "Put commands, hooks, native agent definitions, permissions, and client runtime integration in explicit vendor adapters", exactly the cited claim; AGENTS.md is unchanged between `a8fa3b9` and `c90de14` |
| `docs/cross-vendor-plugin-architecture-brief.md:27-31` | clean — "Agent Plugins 1.0 intentionally does **not** standardize commands, hooks, agent definitions…" matches "what Agent Plugins 1.0 does not standardise" |
| `docs/cross-vendor-plugin-architecture-brief.md:46-56` | clean — the `plugins/<name>/` portable package tree matches "the portable package shape" |
| `docs/cross-vendor-plugin-architecture-brief.md:61-63` | clean — "### 2. Herdr execution layer … Use Herdr as the default vendor-independent execution boundary" matches "the Herdr execution boundary" |
| `docs/cross-vendor-plugin-architecture-brief.md:93-104` | clean — the ten-row client table (Claude Code, Cursor, Qwen Code, Grok Build, Codex/ChatGPT, Gemini CLI, Antigravity, OpenCode, Muse Code, Hermes) matches "the ten-client compatibility table" |
| `docs/ideation/2026-08-25-voice-plugin-ideation.md` (path only) | clean — exists; untouched by the merge |
| `scripts/check_repo.py` (path only) | clean — exists; untouched by the merge |
| `plugins/fleet-core/` (path only) | clean — exists; untouched by the merge |

The merge also touched `docs/README.md`, `docs/runbooks/portable-plugin-port.md`, `docs/engineering-journal/QUEUED.md`, and added `docs/retros/issue-9-2026-08-25.md`; none of these is cited anywhere in the requirements document, verified by full-document citation sweep.

## Observations on the accepted review (not repaired)

None. This run found no defect in the accepted review's findings, repairs, or verdicts; its D1 repair arithmetic and entry identifications were independently re-confirmed by this run's anchor-by-anchor verification.

One factual note for the record: the drift mechanism in this merge was insertion near the TOP of both journal files (newest-first entry order), not an append at the end — which is why the anchors drifted despite the new entries being chronologically later than the cited ones.

## Rubric review record

Deliberately not re-run. This run is scoped to evidence-anchor freshness per the run instructions; the accepted artifact's rubric record (idea phase, ten rubrics, no BLOCK condition) stands unchanged and no input to it was altered by the merge.

## Engine offer

Not run. The operator designated this session as the sole reviewer for the post-integration pass and explicitly excluded external-engine second opinions for it.

## Residual risk from limited evidence

The same residual recorded in the accepted review persists and is unchanged by the merge: the Claude Code hooks documentation claims and the Herdr CLI live-session claims are not reproducible from this repository, and the document already assigns their re-confirmation to planning. Journal line-number anchors remain inherently fragile under this journal's newest-first append pattern; any future merge touching these two files will displace the five repaired anchors again by the inserted line count.
