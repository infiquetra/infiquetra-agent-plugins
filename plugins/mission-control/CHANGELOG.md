# Changelog

## [2.12.2] - 2026-08-24

### Fixed - GraphQL project fields pagination, query-scoped pagination lint, and explicit live parity skip (#584)

- Paginated `QUERY_GET_PROJECT_FIELDS` with cursor and `pageInfo` via `paginate_or_raise` in `get_project_fields` and `board_census.py:fetch_project_fields_census`, eliminating silent field truncation on boards with >30 fields (R1).
- Made `check_pagination.py` query-scoped so unpaginated `first:` query literals inside files that paginate elsewhere are flagged (R2).
- Updated `check_issue_contract_parity.py` to explicitly print `SKIPPED live parity leg: <reason>` on the default (no `--live`) path instead of silently omitting the leg (R3 residual).
- Verified R4 fail-loud behavior is satisfied by existing #609 test suite.
- Made the query-scoped GraphQL guard fail safe rather than fail open: the literal extractor now backreferences its triple-quote delimiter (a stray `'''` previously desynchronized every literal after it) and any `first:` it cannot place inside a query block still gets the original whole-file check, so the narrowed guard is never weaker than the file-scoped one it replaces.
- Recorded a reason on each `# pagination-lint: allow` suppression, matching the convention the helper's own suppression already used.

## [2.12.1] - 2026-08-24

### Fixed - prepared-issue draft revision replacement semantics and multi-fence readiness validation (#785)

- Fixed `sdlc_manager.py` draft preparation write paths to strip existing YAML front matter and top-level H1 titles from source text and prior drafts, ensuring draft revision replaces prior content instead of accumulating duplicate front-matter blocks and titles.
- Added readiness validation blocking check that flags multi-fence drafts (fences > 2) and duplicated section headers (`### ` duplicates and `## `/`### ` duplicate section pairs) before creation.
- Defensively stripped front-matter fences and H1 titles from `_issue_body_for_github` to guarantee created GitHub issue bodies are clean.

## [2.12.0] - 2026-08-16

### Changed - retire the `hermes-task` / `hermes-not-actionable` dispatch markers

- `_ISSUE_TYPE_LABELS` no longer applies either marker. The Hermes orchestrator that read them was frozen on 2026-07-18 (empty repository list, plan phase off, webhook relay stopped and disabled), so they marked cards for a consumer that cannot run.
- Interactive `issue create` now applies the **canonical type labels** instead. That path previously guaranteed only the dispatch marker — not even the type label — so a card whose browser template failed to prefill landed untyped.
- `_HERMES_ACTIONABLE_TYPES` renamed to `_CONTRACT_ISSUE_TYPES`: it names the types that carry the eight-section card contract, which is what it has actually meant since the orchestrator froze.
- Generated template reference: `Hermes actionable: yes/no` becomes `Card contract: required/not required`.
- Prompts, skills, the operator agent, and the triage command updated to match. The claim that "the orchestrator silently skips cards without `hermes-task`" is removed — nothing filters on the label any more.

Paired with the `infiquetra-sdlc` change that removes both labels from the five issue templates. Writers stop here; the label definitions and the GitHub-side labels are retired separately.

## [2.11.0] - 2026-08-15

### Fixed - interactive `issue create` now validates the body before carding it

- `issue create-prepared` has always refused a draft with blocking readiness gaps. Interactive `issue create` had no equivalent: it opened the browser template, took the pasted issue number, and applied labels + board membership with no body check in between, so a blank or half-filled template landed on the board wearing the same labels as a conformant card.
- Adds `_gate_created_issue_body`, called between paste-back and metadata, reusing the existing `validate_card_body_for_context` rather than adding a second contract.
- Scoped to the Hermes-actionable types — `exploration` and `context-update` ship different field sets by design and are not checked.
- A failed issue fetch proceeds with a warning: an API hiccup is not a validation failure and must not strand a good issue.
- Under `--format json` it emits a structured refusal and never prompts, so non-interactive callers cannot hang.
- A failing body is a stop, not a veto: the operator sees the specific gaps plus the exact `gh issue edit` and `flow validate-card` commands, and must opt in explicitly to card it anyway.

## [2.10.2] - 2026-08-08

### Added - house-style presentation contract on the SDLC operator agent (#704)

- `sdlc-operator` agent definition gains a "Presentation contract (Infiquetra house style)" section, copied verbatim from `plugins/house-style/references/subagent-presentation-preamble.md`.

## [2.10.1] - 2026-07-16

### Fixed

- Make `board move` exit nonzero after reporting all project results when an
  item, Status field or option, or mutation is unavailable. Invalid Status
  requests still list provider-read options and never call the mutation.

## [2.10.0] - 2026-07-14

### Added

- Add idempotent `flow assign-mimir --repo REPO --number N`. Before its only mutation it reads
  Team Mimir's exact live coverage from authenticated GitHub, requires an active issue route, an
  open issue, triage-or-higher operator authority, and the repository's existing `intake:mimir`
  label. Success is emitted only after issue readback and includes trigger state, coverage route,
  issue URL, and live Objective project-field values when present.
- Fail closed for unsupported repositories, closed issues, insufficient authority, missing or
  malformed policy, missing trigger labels, API failures, and failed mutation readback. The
  command creates no labels, comments, repository admissions, or alternate credential paths.

## [2.9.0] - 2026-07-14

### Added - ship-policy intent envelope at issue capture (#380)

- **`sdlc_manager.py issue intent-envelope`** — renders the schema-validated ship-policy
  envelope block (`### Intent envelope` + a fenced `intent-envelope` JSON block) for embedding
  in an issue body at capture time, so the operator's autonomy answers are recorded ONCE on
  the issue and `/outcome start` skips its run-start interview (ask-once, S-22). Answer values
  are typed against the fleet interview's closed vocabulary (canonical schema: fleet-core
  `fleet_commons/intent_envelope.py`, loaded through the vendored shim) — off-vocabulary
  values fail loudly at render, never silently coerce.
- **Prepared-issue readiness validates the envelope** — `_readiness_for_prepared_issue` treats
  a present-but-invalid `intent-envelope` block as a BLOCKING gap (fail closed at capture: a
  ship policy a downstream `/outcome start` will trust must be schema-valid the moment it is
  authored). An absent block stays fine — the envelope is optional at capture.

## [2.8.0] - 2026-07-14

### Fixed
- Route every mission-control REST list-fetch (labels, milestones) and GraphQL cursor-paginated
  fetch (project items, issue timelines) through a shared `paginate_or_raise` / `_rest_list_paginated`
  helper that raises `PaginationExhaustedError` instead of silently returning a partial page when a
  paginated fetch never reaches a real terminal signal — closes the "item-list pagination silently
  truncating at 200 of 375 items" fleet defect pattern (#424).

### Added
- Add `board_census.py`: a live-derived board schema census (field/option shape, mirroring the
  context-library's `context_census.py` pattern) committed as `config/board-schema.json`, with a
  `--check` mode that fails on drift from a fresh live derivation and prints an explicit SKIPPED
  line (never a silent pass) when live GitHub Projects access is unavailable.
- Add `check_pagination.py`: a static lint over mission-control's own scripts, skills, commands, and
  agent docs for unguarded `gh` list invocations, bare per-page REST fetches, and GraphQL queries
  that set a page-size arg without ever checking `hasNextPage`.
- Add a third, `--live`-gated reconciliation leg to `check_issue_contract_parity.py`
  (`live_status_option_errors`) that resolves each tracked board's live Status field options and
  flags any `sdlc-schema.json`-declared status that no longer resolves upstream — a genuine
  three-way match (source schema, generated shim, live GitHub) where the prior gate only reconciled
  the first two.

## [2.7.0] - 2026-07-10

### Changed
- Retire Objective as a creatable issue type across the CLI and guidance. Objectives are project
  field options plus Outcome Scorecard docs; Capabilities are top-level by default.
- Make the interactive parent prompt default to no parent and describe native sub-issues as
  decomposition rather than Objective grouping.

### Added
- Add idempotent `flow unlink-sub-issue` for removing accidental or retired parent layers without
  closing either issue.

## [2.6.3] - 2026-07-08

### Fixed
- Validate the loaded SDLC label taxonomy before `labels deploy` calls GitHub, surfacing overlong
  descriptions and missing mission-control issue-taxonomy labels as one clear preflight error.

## [2.6.2] - 2026-07-08

### Fixed
- Add `flow set-field --numbers <n1,n2,...>` plus repeated `--field/--option` pairs for bulk
  project-field updates in one CLI invocation. Bulk mode reuses one field-discovery and
  project-item discovery pass, reports per-item/per-field failures, and exits non-zero after
  reporting when any requested update fails.

## [2.6.1] - 2026-07-08

### Fixed
- Normalize mission-control repo arguments at the CLI boundary so `--repo infiquetra/<repo>`
  behaves like `--repo <repo>` across board, issue, label, milestone, rollout, and flow commands.
  Repos qualified with a non-Infiquetra owner now fail clearly before any GitHub call.

## [2.6.0] - 2026-07-06

### Added — auto-stamped `Recommended Tier Band` on created issues (#368 AC5)

- `derive_tier_band(issue_type)`: type→band map mirroring the shared tier registry's
  work-shape bands — defect/capability → `opus/high`, enhancement/context-update →
  `sonnet/medium`, exploration → `sonnet/low`; `objective` (parent tracking card) carries none.
- The compile path (`_source_to_issue_body`) stamps the derived band as an auto-populated
  `### Recommended Tier Band` body section (mirroring the Lifecycle Origin discipline:
  compile-time, never author-required). Idempotent — a body already carrying the band is not
  double-stamped, so prepare/compile round-trips are safe.
- The card validator needs no change: it checks required H3 sections only, so the extra
  auto-populated section is accepted as-is. Saga's `tier_defaults.parse_tier_band` is the
  consumer (format contract covered by a cross-plugin roundtrip test).

## [2.5.1] - 2026-07-05

### Reformat CHANGELOG title and date separator to canonical grammar (#429)
- Drop the plugin-name suffix from the file title and switch version-heading date separators from
  em dash to hyphen-minus, as part of the release-surface single-source generator work.

## [2.5.0] - 2026-07-04

### Executor-profile lint against the fleet tier palette (#463)
- New standalone `scripts/executor_profile_lint.py`: parses a `Recommended Executor Profile`
  block from `--body-file` or stdin, validates model/effort membership against the canonical
  fleet-core tier palette (resolved through the new vendored `scripts/fleet_commons_shim.py`),
  and enforces the above-sonnet-requires-justification rule via the palette's ordering.
  Exit codes: 0 pass, 1 named findings, 2 no-profile-block. No gh calls — callers pipe the
  issue body in (`gh issue view N --json body -q .body | ...`).

## [2.4.0] - 2026-06-29

### Issue-write verbs for autonomous `/outcome` board-sync (#279)
- New idempotent `issue` subcommands: `close` / `reopen` (PATCH `state`, naturally idempotent),
  `comment` (plain POST; coalescing is the consumer's ledger job), and standalone `label-add` /
  `label-remove` (DELETE; swallows `ApiNotFoundError` 404 = label already absent, propagates other
  errors for the consumer's retry path). Added a `_rest_delete` REST helper.
- These are the reversible board ops that saga's reversibility certificate authorizes and the
  `/outcome` board-sync consumer drives across the saga↔mission-control boundary. Pairs with saga
  0.42.0.

## [2.3.1] - 2026-06-28

### Fixed
- Fixed `issue create-prepared` post-create recovery by resolving issue/PR nodes with
  `issueOrPullRequest(number:)`, keeping GraphQL mutation failures strict, and recording
  resumable sidecar state when board-add or Status assignment fails after issue creation.

## [2.3.0] - 2026-06-27

### Migration notes
- GitHub Project #3 was renamed from **Jeff Intent** to **Operations**. The `--project` value is now
  `operations` (was `jeff-intent`) across all board / metrics / flow / triage commands, and the
  internal board key is `operations` (was `jeff_intent`). Update any saved invocations or scripts
  that passed `--project jeff-intent`. Project number (#3), node id, and the shared `intent_flow`
  workflow are unchanged, so existing cards stay on the board.

### Changed
- Renamed the project surface `jeff-intent` / `jeff_intent` / "Jeff Intent" → `operations` /
  "Operations" across `project-mappings.json`, `sdlc-schema.json`, `sdlc_manager.py`
  (`PROJECT_CHOICES`), command and skill guidance, and the `sdlc-operator` agent prompt. Mirrors the
  canonical rename in `infiquetra-sdlc`. Dated provenance and migration notes preserve the former
  name as historical record.

## [2.2.0] - 2026-06-21

### Changed
- `sdlc-operator` agent: pin `model: sonnet` (was `inherit`). Orchestration work is
  structured/mechanical — Sonnet is the right cost-quality tier (R1/R2a tiering).

## [2.1.0] - 2026-06-17

### Migration notes
- Mission Control now treats Jeff Intent, Asgard, and CAMPPS as the active board surfaces.
  Mount Olympus remains historical context in the vendored SDLC schema and should not be used as
  an active routing target for new work.
- `sdlc-schema.json` resolves from `infiquetra-sdlc` on GitHub `main` before falling back to the
  vendored snapshot, so operators are less likely to read stale local checkout state.

### Changed
- Re-vendored the current `infiquetra-sdlc` schema snapshot at `schema_version: 2026-06-17`.
- Prepared actionable issue drafts now compile fallback bodies from generated SDLC issue-contract
  data instead of hand-written prompt template sections.
- Readiness validation now applies issue-type and risk-aware required fields, including high-risk
  sections and empty-section rejection.
- Updated issue command and skill guidance to route through `issue prepare` for generated contract
  bodies.
- Bumped plugin and marketplace metadata to `2.1.0`.

## [1.6.1] - 2026-05-31

### Changed
- Tracked the `infiquetra-loop` → `saga` rename: updated the ignored runtime-state
  path to `.claude/saga/` and refreshed plugin references in `/issue`, the
  `sdlc-operator` agent, and the `issues` skill.

## [Unreleased]

### Added
- Added `/issue` as the primary issue command surface, with `/issue` retained as a
  compatibility alias.
- Added prepared-issue handoff maturity metadata and source artifact resolution for local files,
  GitHub issue/PR URLs, branch refs, and natural hints such as "from the brainstorm".

### Changed
- Synced the vendored SDLC schema and Asgard prepared-issue readiness with the corrected
  Asgard/Olympus model: sibling target boards with explicit cross-team transfer, not an
  implied Asgard-to-Olympus promotion path.

## [1.6.0] - 2026-05-30

### Added
- Added `issue prepare` to write team-aware Asgard or Mount Olympus issue drafts under
  `docs/sdlc-issue-drafts/` with JSON readiness sidecars.
- Added `issue create-prepared` to re-run readiness, render a full mutation plan, ask for final
  confirmation, repair missing labels/templates, add issues to the requested project, set safe
  starting status, and record the created issue back onto the draft.
- Added Asgard and Olympus readiness profiles. Asgard accepts shaping-quality drafts with mode,
  constraints, risk, and transfer notes; Olympus requires the strict actionable card body,
  expected labels, project presence, author-visible risk, and safe `Backlog` status.
- Added mocked tests for blocked create, declined confirmation, direct create, missing
  labels/templates, missing mapping PR stop, and mapping override creation.

### Changed
- Updated `issues`, `/issue`, `sdlc-operator`, README, and release metadata so
  natural-language requests like "create an Olympus issue from this text" route through prepared
  drafts instead of bypassing readiness checks.
- Bumped plugin and marketplace metadata to `1.6.0`.

## [1.5.0] - 2026-05-30

### Migration notes
- **No breaking CLI changes.** Existing commands continue to work. Operators should update
  installed cache paths from `mission-control/1.0.0` or `1.4.0` to `mission-control/1.5.0` after
  installing this release.
- Current actionable issue templates use `hermes-task`, `needs-plan`, and the type label.
  `needs-analysis` and `needs-triage` remain documented only as legacy auto-label fallback
  labels from `labels.json`.

### Changed
- Added vendored `config/sdlc-schema.json` and taught board/metric helpers to consume schema-backed boards, workflows, WIP limits, and terminal statuses.
- Added live Jeff Intent (#3) and Asgard (#2) project mappings plus explicit `--project` targeting for board add/move.
- Refreshed board, metrics, milestones, labels, rollout, and operator guidance around Jeff Intent, Asgard, Olympus, direct project fields, and deployment-state separation.
- Preserved read compatibility for live/legacy Olympus statuses such as `In Progress`, `In Development`, and `Deployed` while guiding new movement to the current schema.
- Synced `issues` template guidance with canonical issue forms in `infiquetra-sdlc`, including current Hermes actionable labels and required card sections.
- Added a deterministic template documentation generator plus drift guard tests for `templates-reference.md`.
- Restored legacy rollout WIP-limit fallback when schema-backed limits are absent.
- Aligned `sdlc-operator`, `/triage`, and issue/label references so prompts no longer teach
  stale actionable labels or initiative/objective labels as current practice.
- Bumped plugin and marketplace metadata to `1.5.0`.

## [1.4.0] - 2026-05-04

### Migration notes
- **No breaking changes.** The `sdlc-operator` Claude Code subagent (`agents/sdlc-operator.md`) was rewritten to reflect 2026-05-04 reality (Phase C minimum-viable + foundation + interactive flow are all merged). Operators using the prior subagent will see the same trigger phrases but newer command examples.

### Changed (Phase C deferred — sdlc-operator subagent rewrite)
- **`agents/sdlc-operator.md`** — full rewrite. The previous version was authored before Phase C; it referenced removed concepts:
  - Beads/Dolt CLI (`bd ready`, `bd claim`, etc. — removed in PR #114; coordination is now Redis pub/sub + GitHub Projects v2 + Discord per-card threads)
  - "2 project boards" (Strategic Direction + Mount Olympus — Strategic Direction was dropped in PR #16 from `infiquetra-sdlc`; Mount Olympus is the only board)
  - `labels sync-fields` command (deprecated — Initiative/Objective are project fields, not labels per PR #16 in `infiquetra-sdlc`. The command itself still exists in the script for back-compat; `flow set-field` is the canonical mechanism. Removing the command is queued for a follow-up after a deprecation cycle.)
  - `initiative:*` / `objective:*` colon-prefixed labels (anti-pattern; removed in PR #11)
- **The rewrite reflects the cumulative Phase C work** — references the `flow` subcommand group (PR #114), per-user defaults file + typed exceptions (PR #115), the sub-issue-first interactive `issue create` flow (PR #116). Each workflow pattern (full issue lifecycle, board grooming, new initiative/objective setup, objective tracking, blueprint-driven batch creation, triage) updated to use the canonical `flow set-field` / `flow link-sub-issue` / `flow verify-label` / `flow validate-card` helpers.
- The `Today's reality (2026-05-04)` callout is repeated in the agent's docstring + the issue-create workflow section — an operator using the agent learns immediately that today only `Status` is a single-select field on the Olympus board, and the `flow` helpers will silently skip prompts for the other fields until they're created via the runbook.

Plugin manifest: 1.3.0 → 1.4.0. **All deferred Phase C items are now closed.**

## [1.3.0] - 2026-05-04

### Migration notes
- **No breaking changes.** Existing `issue create --repo X --type Y` invocations work identically; new behavior is additive.
- The new flow is interactive by default. Pass `--skip-metadata` for the prior thin-wrapper behavior (just open browser, no post-create work).
- Operators who ran `config init-defaults` (Phase C foundation) get personalized prompt defaults automatically.

### Added (Phase C deferred — Interactive `issue create` rewrite)

The `issue create` subcommand was rewritten as a sub-issue-first, per-project-schema-aware, defaults-driven, capability-adaptive interactive flow. Replaces the previous thin wrapper that just deferred to `gh issue create --web`.

The 10-step flow:
1. Determine type (decision-tree prompt if `--type` not set; default from `~/.claude/sdlc-defaults.json` if present)
2. **Sub-issue-first prompt**: every new card has a parent by default. Operator pastes a `repo#N` ref or types `no` for free-floating
3. Discover which project the repo maps to (per-user `default_project` preferred, else first match)
4. **Per-project schema discovery**: for each candidate field (Initiative, Objective, Status, plus capability-adaptive ones), check if the project actually exposes the field. Silently skip prompts for fields that don't exist
5. Prompt for field values, defaults seeded from `~/.claude/sdlc-defaults.json` (e.g., `default_initiative`, `default_objective`)
6. **Capability-adaptive fields**: for `capability` or `objective` types only, AND only when the project exposes them, prompt for `Capability Size`, `Business Value`, `Technical Risk`, `Target Quarter`
7. Open `gh issue create --repo X --template <type>.yml --web` in the browser; operator fills the body
8. Operator pastes back the issue number (URL or bare integer accepted); skip post-create metadata if blank
9. **Apply post-create metadata**, each step isolated:
   - `hermes-task` for actionable types / `hermes-not-actionable` for objective
   - `board add` to the project board
   - `flow set-field` for each gathered field value
   - `flow link-sub-issue` if a parent was set
10. **Paired-card prompt** (opt-in, default no): create a sibling card on a different repo with the same parent. Useful for cross-service capabilities (backend + Flutter app)

### New CLI flags
- `--parent-ref <repo#N>`: pre-supply the parent ref (skips the sub-issue prompt — useful for batch-create scripts)
- `--skip-metadata`: skip steps 2-10 entirely, just open the browser. Returns to the prior thin-wrapper UX

### New helpers (composable for tests + scripts)
- `_select_issue_type(default=None)` — decision-tree prompt with EOF-safe fallback
- `_prompt_parent_issue()` — sub-issue-first prompt; parses `repo#N` or `yes` followed by ref
- `_project_field_options(project_name, field_name)` — per-project schema discovery; returns None if field doesn't exist (caller skips silently)
- `_prompt_choice(label, options, default)` — generic field-value prompt with options listed + default + `-` to skip
- `_open_gh_issue_create_web(repo, issue_type)` — browser launch helper
- `_prompt_issue_number(repo)` — captures URL or bare int from operator
- `_apply_post_create_metadata(...)` — orchestrates label / board / fields / sub-issue link with per-step error isolation
- `_prompt_paired_card(repo, issue_number)` — opt-in paired-card prompt; returns target/title/body deltas or None

### Tests
- 23 new tests in `tests/test_issue_create_interactive.py` covering each helper in isolation:
  - `_select_issue_type`: typed choice, default-on-blank, garbage-fallback, EOF-safe
  - `_prompt_parent_issue`: direct ref, yes-then-ref, blank-then-ref, no, garbage-warns, EOF
  - `_prompt_choice`: skip-when-no-field, valid option, default-on-blank, dash-skip, invalid-warns
  - `_prompt_paired_card`: default-no, yes-collects-deltas, yes-empty-target-aborts
  - `_apply_post_create_metadata`: hermes-task for actionable, hermes-not-actionable for objective, label-failure-doesnt-abort-others, no-project-skips-fields-but-keeps-link
  - `_PARENT_REF_RE`: realistic refs accepted; `#42`, `repo-only`, garbage rejected
- Total: **92 / 92 passing**

## [1.2.0] - 2026-05-04

### Migration notes
- **No breaking changes.** Existing CLI invocations work identically.
- **Recommended one-time setup**: run `python3 sdlc_manager.py config init-defaults` after upgrading to seed `~/.claude/sdlc-defaults.json` with your gh login + project defaults. Future Phase C PRs will read these as suggestion values in the interactive `issue create` flow.
- **External override still wins**: if you have `$INFIQUETRA_SDLC_PATH/config/project-mappings.json`, it continues to take precedence over the new vendored copy.
- **Exception class names changed (PEP 8 / N818)**: `ApiNotFound` → `ApiNotFoundError`, `ApiAlreadyExists` → `ApiAlreadyExistsError`, `ApiRateLimited` → `ApiRateLimitedError`. Backward-compat aliases retained for the old names; can be removed in a follow-up after a deprecation cycle.

### Added (Phase C deferred — Foundation)

- **Typed exception classes** (`GhApiError`, `ApiNotFound`, `ApiAlreadyExists`, `ApiRateLimited`, `ApiAuthError`, `CardValidationError`). `_gh` now raises the appropriate subclass via `_classify_gh_error` instead of bare `RuntimeError` with a stringy message. Replaces the fragile `"422" in str(e)` substring matching pattern. Downstream callers catch by type:
  ```python
  try:
      _rest_post(...)
  except ApiAlreadyExists:
      # idempotent re-run — treat as success
  ```
  The `flow_link_sub_issue` and `flow_verify_label` helpers were refactored to use this pattern. `flow_verify_label` also now handles a real race (two operators creating the same label simultaneously) via `ApiAlreadyExists` on POST.
- **Per-user defaults file** at `~/.claude/sdlc-defaults.json`. Stores: `assignee` (gh login from `gh api user --jq .login` — *not* OS `$USER`), `default_project`, `default_status`, `default_priority`, `default_initiative`, `default_objective`, `preferred_repos`. Sticky across CLI invocations; future interactive flows read defaults as suggestion values.
  - `load_user_defaults()` / `save_user_defaults()` helpers (atomic write via tempfile + rename; tolerant of missing file + malformed JSON)
  - `get_default(key)` convenience reader
  - New subcommands:
    - `config show-defaults` — display current per-user defaults
    - `config init-defaults [--non-interactive]` — first-run wizard. Interactive by default; `--non-interactive` seeds from `gh api user` + auto-detects `default_project` if exactly one project is mapped (no guessing on multi-project orgs).
- **Vendored `project-mappings.json`** at `plugins/mission-control/config/project-mappings.json`. The plugin now works without an external `infiquetra-sdlc` checkout for canonical Infiquetra projects.
  - New `_resolve_project_mappings(sdlc_path)` helper implements the documented resolution order: external override (`$INFIQUETRA_SDLC_PATH/config/project-mappings.json`) → vendored canonical → remote `gh api` fallback.
  - Project node IDs captured in the vendored file are best-effort + verified 2026-05-04. Field/option IDs are NEVER cached; always fetched live.

### Tests
- 33 new tests across 3 new test files:
  - `test_typed_exceptions.py` (15 tests) — status-code parsing (404/401/403/429/422 disambiguation), 422-already-exists vs 422-validation-failure distinction, integration with `flow_link_sub_issue` + `flow_verify_label` (including race detection)
  - `test_user_defaults.py` (13 tests) — read-side (missing file, malformed JSON, non-object root, unset key), write-side (atomic via tmpfile+rename, parent-dir auto-create, round-trip), `--non-interactive` wizard (gh-login seeded, multi-project no-guess, preserves unknown future keys)
  - `test_project_mappings_resolution.py` (5 tests) — override wins over vendored, vendored used when no override, remote fallback when neither, empty dict on all-three failure, vendored file declares expected canonical state
- Updated 3 PR #114 tests in `test_flow_subcommands.py` to use typed exceptions instead of bare `RuntimeError` with string-matching (the old pattern was testing the old implementation; new tests test the new contract).
- Total: **64 / 64 passing** locally.

## [1.1.0] - 2026-05-04

### Fixed (during PR #114 review)
- **`validate_card_body` header text**: was `"Out-of-scope or non-goals"` (with "or"); home-lab card_validator.py and ALL actionable issue templates use `"Out-of-scope / non-goals"` (with "/"). Every real card would have failed validation with a phantom missing-section error. Corrected to match home-lab exactly. Same iteration also corrects `_PATH_LINE_RE` (now accepts plain filenames + bullet-prefixed paths matching home-lab) and `_CHECKLIST_RE` (now requires `\S` after `[ ]` and accepts `*` bullets matching home-lab).
- **Drift-guard test**: added `test_required_headers_match_actual_issue_templates` that loads the real issue templates and verifies every `_REQUIRED_H3_HEADERS` entry has a matching `label:` in capability/enhancement/defect.yml. This is the test that would have caught the original "or" vs "/" bug.
- **Pre-existing test breakage**: `tests/test_sdlc_manager.py` had a `TestBeadsClaim` class referencing the deleted `beads_claim` function. Class deleted; CHANGELOG note added in the test file.
- **WIP-limits test fixture**: was using the old `beads_config` config-key (which now degrades to `{}`); the override test passed only by coincidence. Renamed fixture to `legacy_rollout_config`; tightened assertion to verify the OVERRIDDEN column (Ready) renders with the override limit, not just any column happening to have a "5" in its render.
- **`flow_validate_card` exit-code path**: was calling `sys.exit(1)` directly, bypassing main()'s formatted-error path and breaking programmatic callers. Now raises `CardValidationError` (RuntimeError subclass) which main() catches; preserves the standard CLI exit code behavior + lets future callers inspect the failure.
- **`_resolve_project_field` error message**: now includes a hint pointing at the field-creation runbook in `infiquetra-sdlc/docs/operations/operational-reference.md` when a field doesn't exist.
- **Stale `# BEADS` banner**: removed (Beads removal had left an empty banner in the argparse section).
- **Duplicate `import re`**: removed (validator block had a redundant import; top-level `import re` at line 61 already covers it).
- **Unused `project_id_check` variable**: replaced with `_, items = ...` discard idiom (consistent with `board_wip` pattern).
- **README.md**: removed the "Beads coordination" capability bullet + stale `bd` CLI prerequisite + stale `Beads Operations` section + stale `config/beads-config.json` row. Added `Flow Operations` section with the 6 new commands.

### Added
- New `flow` subcommand group — operator-facing GraphQL + REST helpers:
  - `flow set-field` — set a single-select project field on a card (Initiative, Objective, Status, etc.)
  - `flow field-options` — list current options for a project field (live discovery, IDs not cached)
  - `flow discover-project` — resolve which project a repo maps to
  - `flow link-sub-issue` — link child as native sub-issue of parent (cross-repo, idempotent)
  - `flow verify-label` — self-healing label create (404 → create, exists → no-op, other errors raise)
  - `flow validate-card` — pre-flight check an existing issue body against the card_validator schema
- New `validate_card_body()` Python helper — mirrors home-lab card_validator.py's high-leverage checks (6 required H3 headers, AC has ≥1 checklist, Verification has ≥1 fenced code block, Files-expected has ≥1 path-like line, no placeholder-only sections)
- New `flow` skill (SKILL.md) describing the `flow` commands + idempotency contract + hard rules + integration with the blueprint-to-issue workflow
- 20 tests in `tests/test_card_validator.py` and `tests/test_flow_subcommands.py` covering: validator schema rules, idempotency contracts, error classification (404 vs auth vs server), live-discovery vs cached, helpful error messages with current options listed

### Changed
- Renamed `beads_config` config-key to `legacy_rollout_config` in `load_config` and downstream readers (`board_wip`, `rollout_status`, `rollout_update`, `config_show`). The underlying file (`beads-config.json`) was already removed from infiquetra-sdlc on 2026-04-26; the key now degrades gracefully to `{}` for back-compat. Comment in `load_config` documents the migration.

### Removed
- `beads` subcommand group (`ready`, `claim`, `update`, `complete`, `status`)
- `_bd` shell helper for invoking the `bd` CLI
- All `beads_*` Python functions
- The Beads/Dolt coordination layer was removed from Mount Olympus on 2026-04-26 (see `infiquetra-sdlc/docs/engineering-journal/narratives/2026-04-26-beads-dolt-removed.md`); the agent fleet now coordinates via Redis pub/sub + GitHub Projects v2 + Discord per-card threads. The plugin's `beads` commands targeted infrastructure that no longer exists.

### Migration notes
- Operators previously running `sdlc_manager.py beads <action>` will get an `argparse` error. There is no replacement — the underlying coordination has moved off Beads entirely. Use `gh` + the new `flow` commands for direct board operations.
- The `flow set-field` command is the canonical mechanism for Initiative + Objective assignment per the 2026-05-03 DECISION (see `infiquetra-sdlc/docs/engineering-journal/DECISIONS.md`). The fields don't exist on the Olympus board today; create them via the operator runbook in `operational-reference.md` before using `flow set-field`.

## [1.0.0] - 2026-03-29

### Added
- Initial release of mission-control plugin for the Mount Olympus agent team
- Updated wording to use Infiquetra conventions consistently
- 6 skills: board, issues, labels, metrics, milestones, rollout
- 4 commands: /board, /issue, /metrics, /triage
- 1 agent: sdlc-operator
- Python CLI: sdlc_manager.py (zero external dependencies, gh CLI wrapper)
- New: beads resource group for Beads/Dolt task coordination
- Removed: Rally sync, GHE hostname requirements, Chainproofers/Identifiers team split
- Coordination model: Beads-first with GitHub Issues as backing store
- Notifications: Discord (not Slack)
- 2 project boards: Strategic Direction + Mount Olympus Operations
