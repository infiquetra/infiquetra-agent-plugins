---
date: 2026-08-27
kind: doc-review
target: docs/plans/2026-08-27-auralis-c3-adapter.md
reviewed_revision: 34760140a3620e0f4559dca4944f1c729c27697f
branch: orch/auralis-c3-adapter-docreview-c3-plan
classification: implementation plan
blocked: true
---

# Document review — Auralis C3 Claude adapter implementation plan

**Verdict: NOT READY / BLOCKED.** The plan preserves the central content-custody rules, but eight open priority-one (P1) findings would let implementation ship without a real rejection-to-fallback path, lose turn evidence between processes, accept Markdown that requirement R121 (the plain-spoken-text submission rule) requires it to reject, or pass helper tests while the declared Model Context Protocol (MCP) process does not run.

## Applied fixes

No fixes were applied. The operator required review-only treatment of the plan, so this artifact is the only repository change.

## Review result

This review is blocked by eight P1 findings; four priority-two (P2) findings add meaningful wire, unit-custody, and verification risk.

| field | value |
|-------|-------|
| target | `docs/plans/2026-08-27-auralis-c3-adapter.md` |
| reviewed revision | `34760140a3620e0f4559dca4944f1c729c27697f` on `orch/auralis-c3-adapter-docreview-c3-plan`; target blob `999de8ab157ca3e6288e6d2fae0a3c83367f7d62` |
| wire authority reviewed | read-only local `docs/bridge-v1-from-c10.md` for Auralis Core capability slice C10, Secure Hash Algorithm 256-bit (SHA-256) `eb47d141e5c1b87bae0bd1c0799386a3aa8806635251db14fc806469b5db19eb` |
| classification | single implementation plan; normal readiness-skeptic pass |
| blocked | true — unresolved P1 findings remain |
| findings | 0 priority-zero (P0), 8 P1, 4 P2, 0 priority-three (P3) |
| applied fixes | none |
| review artifact | `docs/reviews/2026-08-27-auralis-c3-adapter-plan-doc-review.md` |
| override rationale | none |
| linked issue / plan | `infiquetra/infiquetra-agent-plugins#46`; target plan above |

The local bridge document was treated as the normative wire authority exactly as directed. The Voice 0.2.1 package behavior and exploration X1 (the PreToolUse payload-shape check) were accepted as established and were not re-derived.

## Readiness summary

The plan cannot safely drive implementation because the local fallback record is not a handoff to Auralis Core, and the five-route wire exposes no adapter operation that supplies fallback text or changes the turn to `fallback_accepted`. The plan also relies on a bridge document it calls committed even though that file is absent from the reviewed Git revision and locally excluded from Git.

Several sharp constraints are otherwise stated correctly. Authored text is rejected rather than cleaned, accepted text is intended to cross the adapter unchanged, preferences are transmitted as instructions rather than applied, and a bound non-Auralis turn gets the negative origin case with no rendering expectation.

All declared implementation file sets stay in this repository, and none plans an `infiquetra/auralis`, speech-provider, audio-capture, playback, or user-interface change. The declared unit file lists do not overlap, standard-library Python and `unittest` are explicit, and the hosted `Validate` workflow is acknowledged; findings F7 and F9 show where undeclared files or shared test custody would nevertheless become necessary.

## Remaining findings by priority

Every finding is open and requires a plan correction before implementation dispatch.

| id | priority | status | summary |
|----|:--------:|:------:|---------|
| F1 | P1 | open | The wire authority is not committed or reproducibly pinned, so a clean checkout loses the document and fails the repository's Markdown-link check. |
| F2 | P1 | open | An unreplaced R121 rejection is only labeled `fallback` in adapter-local JavaScript Object Notation (JSON); no planned handoff supplies requirement R22's fallback content or requirement R23's visible fallback marking in Core. |
| F3 | P1 | open | No test proves requirement R122 (the unreplaced-rejection fallback rule) by running an actual rejected submission through completion and observing the resulting marked fallback path. |
| F4 | P1 | open | Multiple processes update one whole-file turn record without a transaction, so atomic replacement can still lose submissions, rejection reasons, observations, or outcome. |
| F5 | P1 | open | The R121 gate deliberately reuses an incomplete Markdown recognizer and therefore permits Markdown forms outside the Voice 0.2.1 cleanup subset. |
| F6 | P1 | open | Tests call the MCP server loop in process instead of running the command Claude will launch, contrary to the repository's executable-entrypoint rule. |
| F7 | P1 | open | Implementation unit U1 reads two new environment variables outside the package's sole settings reader while assigning neither `settings.py` nor its tests to a unit. |
| F8 | P1 | open | The lost-response retry case can return `duplicate_rendering` after Core already accepted speech, but the plan does not define how the adapter records and reconciles that accepted turn. |
| F9 | P2 | open | The shared independent-literals bridge stub is promised but has no named file or unit owner. |
| F10 | P2 | open | Hypertext Transfer Protocol (HTTP) and hook timeouts are called “short” or “stated” without any numeric values. |
| F11 | P2 | open | U1's malformed-wire scenarios do not prove the contract's full token and Core-identifier grammar. |
| F12 | P2 | open | The requirements document is said to be pinned at `b49de1b`, but both recorded URLs point to mutable `main`. |

### F1. The claimed committed wire pin does not exist in the reviewed revision

The plan's most important evidence source disappears in a clean checkout.

The plan calls `docs/bridge-v1-from-c10.md` a “verbatim working copy” that is “committed in this repository” and says adapter assumptions are pinned to that committed copy (plan lines 48–62). At the reviewed revision, `git show HEAD:docs/bridge-v1-from-c10.md` exits 128 because the file is not in Git; it is a read-only local file excluded by `.git/info/exclude`.

This is not only a provenance wording error. The tracked plan links to the absent path, while `scripts/check_repo.py` lines 291–307 rejects missing local Markdown targets and the hosted `Validate` continuous integration (CI) workflow runs that checker after a clean checkout; the current local check passes only because the excluded file is present in this worktree.

Required disposition: make the exact reviewed contract bytes available from a durable immutable pin that clean implementation and CI checkouts can resolve. The plan must then describe that real custody mechanism rather than call a local excluded file committed.

### F2. The R121 rejection path never reaches an actual R22/R23 fallback

Writing the word `fallback` to local adapter state does not make Core accept or mark a fallback.

The plan says the Stop hook suppresses the legacy local speech path and only records outcome `fallback` when no authored rendering was accepted (plan lines 163–167, 292–305, and 629–634). It then explicitly excludes sourcing the full written response to Core (lines 697–699), even though R22 requires that response to become the fallback and R23 requires the fallback to be visibly distinguishable.

The C10 contract exposes only authored submission at `POST /v1/rendering` (contract lines 102–110 and 213–265). It exposes `fallback_accepted` as Core state and assigns `acceptFallback()` to audio capability slice C5 (lines 202–209 and 331–336), but the plan names no mechanism that carries the Stop hook's `last_assistant_message` or completion signal to that mechanism.

Required disposition: name the already-owned C10/C5 handoff that consumes the exact completed response and transitions the captured identifier pair to marked fallback. If no such handoff exists, the bridge or slice boundary must be resolved before C3 dispatch; a local outcome label cannot substitute for it.

### F3. The R122 test plan joins two fixtures, not two production boundaries

The described tests can pass while the real rejection-to-fallback handoff is broken.

Implementation unit U3's acceptance example AE26 test rejects Markdown and then accepts a replacement (plan lines 554–575), so it never exercises R122's unreplaced case. Implementation unit U4 starts its Stop-hook scenario from “a prior gate rejection in the record” (lines 629–632), which can be constructed directly and does not prove that `submit_spoken_rendering` wrote what the real Stop hook later reads.

Required disposition: add one scenario that calls the actual MCP tool with Markdown, observes the named rejection and no wire forwarding, supplies no replacement, executes the real completion boundary, and observes the same turn become marked fallback through the mechanism that closes F2. The test must fail if the submission record schema, session/identifier join, completion handoff, or fallback marker drifts.

### F4. Atomic replace does not protect the shared turn record from lost updates

The plan confuses a complete file write with a transaction across writers.

The UserPromptSubmit hook creates the record, the long-lived MCP process appends submissions, the PreToolUse hook appends observations, and the Stop hook settles the outcome (plan lines 149–165, 499–502, 543–552, and 599–608). Those are separate processes performing read-modify-replace operations on one JSON file.

The risk section says atomic write-replace and one writer per “field family” contain the race (lines 731–735), but two writers can read the same prior document and each replace it with a complete yet incomplete update. That interleaving can erase the named R121 rejection or an accepted disposition and cause the wrong R122 result.

Required disposition: choose one standard-library transaction design for all record mutations, assign its file ownership, and add deterministic interleaving tests that fail on lost updates. Atomic replacement may remain the torn-write defense, but it is not the concurrency mechanism.

### F5. The planned Markdown detector is known to be incomplete

R121 cannot be proved by copying a recognizer whose documented scope is narrower than Markdown.

The plan limits the gate to fences, hash-prefixed (ATX) headings, paired emphasis, inline code, inline links/images, lists, blockquotes, horizontal rules, and table pipes (plan lines 490–517). The source it proposes to reuse says it is a small line-and-regex cleanup pass and that fidelity beyond its tested classes is not a version-one goal (`plugins/voice/scripts/text_cleanup.py` lines 1–13).

Setext headings, reference-style links, autolinks, and indented code blocks are concrete Markdown forms outside that list. A gate built literally from the plan would accept them as plain text even though R121 requires a rendering containing Markdown syntax to be rejected at submission.

Required disposition: define the complete rejected syntax contract and tests at the agent-facing boundary, including negative cases for ordinary punctuation. The implementation must still return a named rejection and must never expose a cleanup or rewrite path.

### F6. The declared MCP executable is never tested as Claude runs it

In-process loop tests do not prove that the installed command starts, imports, frames, and answers over standard input/output.

The plan declares `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/mcp_server.py` through `com.infiquetra.claude/mcp/servers.json` (plan lines 385–393 and 645–676). U3 instead drives an imported server loop over injected byte streams (lines 543–575), while U5 checks only that the path exists and says no behavior suite is added.

`AGENTS.md` lines 63–66 requires an executable entrypoint to be run the way a user runs it because separate component tests have previously missed broken imports. Required disposition: assign a test that launches the exact declared argv from an installed-root-shaped directory and completes MCP initialize, tools/list, a rejected tools/call, and an accepted tools/call over real process pipes.

### F7. Identity discovery violates the package's closed environment-reading contract

The unit cannot follow both its file list and the existing Voice settings rule.

U1 directs `adapter_identity.py` to read `HERDR_PANE_ID` and `HERDR_BIN_PATH` from the environment (plan lines 418–445), while Key Technical Decision 9 (KTD9) says `settings.py` and its closed `SETTING_NAMES` remain untouched (lines 362–373). The existing module says it is the whole package's sole environment reader and that nothing outside its eight-name tuple is read (`plugins/voice/scripts/settings.py` lines 1–7 and 79–90).

Neither `plugins/voice/scripts/settings.py` nor `plugins/voice/tests/test_settings.py` belongs to any implementation unit. Required disposition: explicitly reconcile the C10-mandated identity context with the package rule, then give the chosen files and regression tests to exactly one unit without overlapping another unit's custody.

### F8. Lost accepted responses have no defined local outcome

The retry rule can turn a successful authored rendering into an apparent rejection unless the plan defines reconciliation.

The C10 contract permits one byte-equivalent retry after a rendering response is lost and states that an earlier acceptance then returns `duplicate_rendering` (contract lines 317–322). The plan says every Core rejection, including `duplicate_rendering`, is relayed as `rejected_by_core` and recorded, while completion is authored only when the captured turn reached an accepted authored rendering (plan lines 543–575 and 292–305).

No scenario loses the first accepted response, receives `duplicate_rendering` on the retry, and then checks both the agent result and the settled turn outcome. Required disposition: define how retry context and/or the exact `GET /v1/current` state establishes the local authored outcome for this case, and prove that it cannot become fallback or invite an unsafe replacement.

### F9. The shared bridge stub has no file owner

The test architecture promises one fixture that no unit is assigned to create.

The plan says every wire literal is centralized in one module and one stub fixture (plan lines 57–66), and U3 says it uses the U1 stub (lines 543–552). U1's file list contains only production modules and two `test_*.py` files; no reusable stub module is named (lines 413–421).

Required disposition: name the shared fixture path, its import contract, and its sole owning unit. Otherwise U3 must either create an undeclared file, import another test module as production test infrastructure, or duplicate the literals the plan says are centralized.

### F10. Runtime deadlines remain choices for implementers

The lease and prompt hot paths need numbers, not adjectives.

U1 requires “stated short timeouts” for every HTTP call, and U4 adds hook entries with “stated timeouts,” but no connect, read, overall-call, UserPromptSubmit, or PreToolUse value appears (plan lines 432–445 and 583–608). Those choices affect whether the 5,000 ms renewal point is met and how long every prompt can stall during bridge trouble.

Required disposition: state the numeric timeout budget for each operation and hook, plus the expected behavior when it expires, and add clock/deadline scenarios at the boundary that owns it.

### F11. Strict wire validation is not fully mutation-provable

The named malformed cases leave accepted contract violations that the plan calls fail-closed.

The contract requires a 43-character unpadded base64url token and lowercase Version 4 universally unique identifiers for Core-assigned binding and turn identifiers (contract lines 25–40 and 311–315). U1 names token length, empty-token, type, and schema cases but no invalid base64url alphabet/padding case and no malformed, uppercase, or wrong-version Core identifier case (plan lines 432–464).

Required disposition: add explicit malformed fixtures for those contract literals and assert that no presence or rendering request follows. The tests should also mutate each guard once so a relaxed validator is observed failing before restoration.

### F12. The requirements pin is a moving branch URL

The plan's requirement source cannot be reconstructed from the links it records.

Frontmatter and the namespace note link to `.../blob/main/docs/brainstorms/2026-08-26-auralis-v1-requirements.md` while saying the document is pinned at `b49de1b` (plan lines 1–6 and 41–46). The unattended-decisions log repeats that the URL is pinned even though `main` can move (lines 774–776).

Required disposition: replace the moving links with an immutable commit permalink and preserve the exact source revision in the acceptance evidence. This does not require an `infiquetra/auralis` edit.

## Unresolved work question

One cross-slice answer is required before implementation can proceed: which already-owned C10/C5 mechanism receives the Stop hook's exact full written response and changes the captured `(binding_id, turn_id)` to `fallback_accepted` after an R121 rejection receives no replacement? The reviewed five-route contract names no such adapter handoff, and the plan must not invent one or silently substitute a local JSON label.

## Verification evidence

The current worktree's repository checker passes, but that result is not reproducible from the reviewed commit because the excluded bridge file masks the broken tracked link.

| check | result |
|-------|--------|
| target and contract read completely | pass |
| target tracked and unchanged during review | pass; blob `999de8ab157ca3e6288e6d2fae0a3c83367f7d62` |
| contract available in reviewed Git revision | fail; `git show HEAD:docs/bridge-v1-from-c10.md` exits 128 |
| local contract integrity for this review | pass; read-only file, SHA-256 `eb47d141e5c1b87bae0bd1c0799386a3aa8806635251db14fc806469b5db19eb` |
| `PYTHONDONTWRITEBYTECODE=1 python3 scripts/check_repo.py` in the populated worktree | pass; limited by the excluded local file above |
| the same repository checker against a clean `git archive HEAD` | fail as predicted; three broken-link errors for `../bridge-v1-from-c10.md` |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q` | pass; 755 tests |
| review-artifact whitespace and repository `git diff --check` | pass |

## Residual risk from limited evidence

No external or live Auralis source was consulted; the operator-designated local C10 document was the sole wire authority. The review therefore does not claim that the local bytes match the current Auralis run branch beyond the supplied statement.

The current plan's Claude plugin lifecycle claims were not re-researched. F6 requires the implementation to prove the declared process in the installed shape, which is the relevant readiness closure for this repository.

No formal idea-, issue-, or specification-phase rubric ran because the explicit target is a single implementation plan. No external-reviewer panel was requested or dispatched.
