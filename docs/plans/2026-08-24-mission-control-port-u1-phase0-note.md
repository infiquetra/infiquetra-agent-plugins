# U1 Phase 0 note — mission-control port descriptor and entry criteria

**Date.** 2026-08-24 · **Unit.** U1 of the [mission-control portable-port run
plan](2026-08-24-mission-control-port-run-plan.md) · **Child issue.**
infiquetra/infiquetra-agent-plugins#11 · **Runbook.**
[portable-plugin-port.md v1.0.0](../runbooks/portable-plugin-port.md) Phase 0

This note is the committed Phase 0 record the run plan and child #11 require:
the validation-rule inventory (predicate + authority per rule), the Python
floor with the explicit interpreter path, the non-goals, the upstream-suite
evidence, and the `test_prompt_alignment.py` premise verdict. The custody
table itself lives in `ports/mission-control.json`; the two no-precedent
custody decisions are journaled in `docs/engineering-journal/DECISIONS.md` in
the same commit.

## Pinned source

- Upstream repository `infiquetra/infiquetra-claude-plugins`, commit
  `84eaf042f0e350005f7eddf8e7d80da25c12119d` (plugin version 2.12.2, read from
  the client manifest at the pin by `sync_vendor_source.source_version`).
- The package inventory at the pin is 60 files. The custody table in
  `ports/mission-control.json` names 59 of them; the 60th,
  `.claude-plugin/plugin.json`, is assigned by `classify_source_tree` through
  `source.manifest_path` rather than in the table (the manifest is the fixed
  input of the `relocate-claude-manifest` transform, not a custody choice).
- Verified mechanically at authoring time: `classify_source_tree` over the
  pinned scratch tree reports zero unclassified and zero absent paths, and a
  set comparison of the table against `git ls-tree -r` at the pin is an exact
  match (42 byte copies, 9 transforms, 5 client byte copies, 1 superseded,
  2 dropped, 1 relocated manifest).

## Custody decisions without UniFi precedent

1. **`when_to_use` transform custody.** All seven `SKILL.md` files carry a
   `when_to_use:` frontmatter key that is not among the six fields
   `SKILL_FRONTMATTER_FIELDS` permits (`scripts/check_repo.py:123-130`). They
   are classified in `entrypoint_transforms` — the descriptor's only transform
   custody — for the versioned `normalize-skill-frontmatter` fold the sync
   unit (U3) implements per plan KTD3. The alternative of normalizing upstream
   is rejected because `when_to_use` is functional in Claude Code skill
   listings. Per plan KTD7 this descriptor does not anticipate the rule-name
   field; U3 owns the schema-3 migration and never revisits these classes.
2. **Tests inside the package.** The 21 carried upstream test files are byte
   copies under `plugins/mission-control/tests/`, inside the provenance
   closed-set check, rejecting the pilot's one-off of repo-root tests tracked
   by fleet-core's informal, unvalidated `release_surface` key.
3. **`tests/test_prompt_alignment.py` dropped** — see the premise verdict
   below. This is the third non-obvious custody decision and is journaled
   alongside the two the child names.

## `test_prompt_alignment.py` premise verdict (doc-review F2)

**Verdict: the premises FAIL under this repository's layout. Custody finalized
here: `dropped_from_source`.** The test is a whole-upstream-repository drift
guard. It computes the repository root as three levels above its own
`tests/` directory and reads both package-internal and repository-level
surfaces. Premise by premise, under the portable layout:

| Read site | Premise under the portable layout | State |
| --- | --- | --- |
| `PLUGIN_ROOT/.claude-plugin/plugin.json` | The Claude manifest is relocated to `com.infiquetra.claude/plugin.json` by `relocate-claude-manifest` v1; the package-root `plugin.json` is the target-owned portable manifest (U4) | FAILS (relocated) |
| `ROOT/.claude-plugin/marketplace.json` | Absent from this repository — probed: no root `.claude-plugin/` exists; the Claude marketplace convention is not carried by the portable catalog | FAILS (absent) |
| `PLUGIN_ROOT/agents/sdlc-operator.md` | Client byte copy; lands under `com.infiquetra.claude/agents/` | FAILS (relocated) |
| `PLUGIN_ROOT/commands/triage.md`, `commands/issue.md` | Client byte copies; land under `com.infiquetra.claude/commands/` | FAILS (relocated) |
| `PLUGIN_ROOT/README.md` | Superseded by the target-owned portable README (U4); the test asserts upstream README prose | FAILS (superseded) |
| `ROOT/plugins/saga/skills/handoff/SKILL.md` | Absent from this repository — probed: `plugins/` carries `fleet-core` and `unifi` only; the saga plugin belongs to the upstream repository, outside this port's scope | FAILS (absent) |
| Package-internal byte copies (`config/sdlc-schema.json`, `scripts/sdlc_manager.py`, `skills/**`) | Present and byte-equal at the pin | satisfied, but moot |

Six structural premise failures, every one caused by a deliberate portable
layout decision (manifest relocation, client-extension relocation, README
supersession, no marketplace/saga surfaces in this catalog). A byte copy
would ship a test that errors at collection in the U6 package suite; editing
its content to make it pass is the custody violation the plan's U6 names. The
custody decision is therefore recorded here, in the descriptor, and in the
journal, per the run plan's F2 disposition ("premise verification moved into
U1's Phase 0; custody finalized in U1/U3 before synchronization"). Its
upstream value is unchanged: the guard remains green in the upstream suite at
the pin, where its premises hold.

## Validation-rule inventory (runbook entry criterion)

Five validation rules travel with the package. Each is listed with its named
predicate and named authority — a standard-library function, a specification,
or a schema, per the runbook — as audited at the pin. U7 (runbook Phase 2)
turns this inventory into class-first corpora and authority-derivation tests;
the predicates and authorities below are its input.

1. **Card validator** — `validate_card_body` in `scripts/sdlc_manager.py`
   (around line 2363 of the pinned source), exercised by
   `tests/test_card_validator.py`.
   - **Predicate.** An SDLC issue body is acceptable at ingest iff it carries
     every always-required H3 header (Objective, Intent, Out-of-scope /
     non-goals, Files expected to change, Tests to add or update, Context
     library links, Acceptance criteria, Verification), the Acceptance
     criteria section has at least one checklist item naming a runnable check,
     Verification has at least one fenced code block, Files-expected has at
     least one path-like line, and no section is placeholder-only (the
     Context library links `_none_` declaration excepted). The
     risk-conditional matrix is the home-lab gate's job; the body-only shim
     has no Risk/issue-type input.
   - **Authority.** `home-lab/ansible/roles/hermes_orchestrator/files/card_validator.py`
     in the home-lab repository (external checkout). The package vendors only
     the DATA extracted from it — `config/generated/issue_contract_data.py`
     and `config/generated/issue_contract_shim.py`, generated by
     `tools/docs/gen_issue_contract.py` in `infiquetra-sdlc` — never the
     algorithm. U7 derives verdicts live from the home-lab checkout and
     self-skips loudly when it is absent (plan KTD5).
2. **Issue-contract parity** — `config/generated/check_issue_contract_parity.py`
   with its `issue_contract_data.py.sha256` and `issue_contract_shim.py.sha256`
   sidecars, exercised by `tests/test_issue_contract_parity.py` and by the
   upstream CI's standalone stdlib-only gate step.
   - **Predicate.** The vendored generated modules are byte-identical to the
     pinned artifacts: recomputed SHA-256 equals the committed sidecar for
     each.
   - **Authority.** The two committed `.sha256` sidecar files at the pin. The
     generator itself (`tools/docs/gen_issue_contract.py`) lives in
     `infiquetra-sdlc`, outside the pinned tree, so a portable consumer cannot
     re-derive the modules from source; the `--live` parity leg prints an
     explicit SKIPPED line when that repository is unavailable — a skip, never
     a silent pass (the test suite asserts both behaviors).
3. **Pagination lint** — `scripts/check_pagination.py`, exercised by
   `tests/test_check_pagination.py` and `tests/test_pagination_helper.py`.
   - **Predicate.** No GitHub list call site in the package truncates
     silently: a raw `gh ... item-list` call must carry `--limit` on the same
     line; a REST list fetch must go through the shared
     `_rest_list_paginated()` helper rather than a bare `_rest_get(...per_page=...)`;
     a GraphQL query literal setting a page-size arg (`first:`) must check
     `hasNextPage`. Exit 0 = no unguarded call sites; exit 1 = at least one
     violation.
   - **Authority.** The lint's own pattern set at the pin (package-local,
     standard-library-only), whose corpus is the package's own script and
     reference-doc call sites.
4. **Prompt-alignment guard** — `tests/test_prompt_alignment.py`.
   - **Predicate.** The package's prompts, references, and release metadata
     agree with the current Asgard/CAMPPS model: manifest/marketplace version
     parity, current template label pairs, field-first hierarchy guidance, the
     card-contract split in the operator agent, Olympus retirement across all
     active surfaces, and template-free saga handoff routing.
   - **Authority.** The whole upstream repository layout: the root
     `.claude-plugin/marketplace.json`, the package-local Claude manifest,
     `plugins/saga/skills/handoff/SKILL.md`, and the unrelocated agent and
     command paths. **The guard is dropped from the portable package** — see
     the premise verdict above. What a portable consumer can honestly establish
     is that the byte-copied prompts and references still say what the pinned
     upstream says they say; the layout premises cannot be re-established here,
     and U7 records that limit rather than pretending to enforce it.
5. **Template-sync drift guard** — `scripts/sync_template_docs.py` with
   `tests/test_template_sync.py`.
   - **Predicate.** The skill and reference documentation that describes SDLC
     issue templates agrees with the canonical templates: display names match,
     the actionable required-field set matches, and the retired terms
     (`needs-analysis`, `needs-triage`, `Business Value`, ...) do not appear.
   - **Authority.** The canonical template directory
     `.github/ISSUE_TEMPLATE/*.yml` inside the `infiquetra-sdlc` checkout,
     resolved by `sync_template_docs.sdlc_path()` — `INFIQUETRA_SDLC_PATH`
     environment override, else the default sibling checkout path. The test
     self-skips with an explicit reason when the checkout is absent (the
     convention KTD5 reuses). On the run machine the checkout is present, so
     this leg executes for real: it ran unskipped in the Phase 0 upstream
     suite below.

## Python floor

- **Floor.** Python 3.12, per `tests/test_python_floor.py`'s
  `PYTHON_FLOOR = (3, 12)` (this repository's single authority) and the
  upstream declaration `requires-python = ">=3.12"` with 3.12 pinned across
  the upstream CI jobs. The floor is a minimum, not a pin.
- **Floor interpreter on the run machine, by explicit path.**
  `/opt/homebrew/bin/python3.12` — Python 3.12.13. Never as bare `python3`.
  The Phase 0 suite and every later floor-bound run use this path (U8's
  assessment venv is built from it and extended with PyYAML, which
  `sdlc_manager.py` imports at module scope, line 83 at the pin).

## Non-goals

Carried from the child and the contract; binding on this unit:

- No file synchronization and no `plugins/mission-control/` content — that is
  Lane A (U3). This unit's descriptor deliberately names a tree that does not
  exist yet; full `check_repo.py` green is the assembled integration-branch
  state.
- No fleet-core changes (U2) and no anticipation of the schema-3 rule-name
  field (U3 owns every schema-touching edit; plan KTD7).
- No edits to `infiquetra/infiquetra-claude-plugins`. Upstream defects are
  filed upstream by U9, never repaired downstream; the stale `2.1.0` cache
  paths in the four commands and the agent are carried verbatim when Lane A
  syncs.
- No changes to the vendored `config/project-mappings.json` semantics; this
  repository is added to no board mapping.
- No live GitHub calls anywhere in this unit beyond reading the pinned
  upstream tree.
- No client remediation, marketplace manifests, or distribution work.

## Upstream-suite evidence (runbook entry criterion, doc-review F5 procedure)

The upstream mission-control suite is **green at the pin**: 275 tests
collected, **275 passed** in 3.48s.

- **Procedure.** A disposable scratch clone of the local upstream repository
  was created by a read-only git operation (`git clone --no-hardlinks`) into
  scratch space, and the pinned commit
  `84eaf042f0e350005f7eddf8e7d80da25c12119d` was checked out there. The suite
  ran from the scratch clone, never from the authoritative checkout.
- **Interpreter and dependencies.** `/opt/homebrew/bin/python3.12`
  (3.12.13) in a scratch-confined virtualenv with `pytest` 9.1.1,
  `pytest-cov` 7.1.0, `PyYAML` 6.0.3 — nothing else; the suite's remaining
  imports are standard library or package-local.
- **Command.** From the scratch root:
  `.u1-venv/bin/python -m pytest plugins/mission-control/tests -v --cov=plugins --cov-report=term-missing`
  (the upstream `addopts` coverage shape, so the run matches upstream CI
  semantics).
- **Confinement.** Every pytest cache and coverage output landed inside the
  scratch clone (`.pytest_cache/`, `.coverage`); the authoritative checkout
  was never written to.
- **Authoritative checkout record.** Before the run: HEAD
  `d82895133886e8843c8cf888eada3fed036ecb7e` (the checkout deliberately does
  not sit at the pin — the second reason an in-place run is not read-only,
  besides upstream pytest writing coverage by default), working tree carrying
  26 pre-existing untracked `docs/sdlc-issue-drafts/` files and zero tracked
  modifications. After the run: HEAD identical and `git status --porcelain`
  byte-identical to the before snapshot (diff empty).
- **Template-sync leg.** Executed for real, not skipped: the run machine
  carries the `infiquetra-sdlc` checkout the guard's authority resolves to.

## Decisions and deviations recorded by this unit

1. **`tests/test_port_config.py` extended for the landing-model interim
   state.** The module's two repository-state tests previously asserted every
   descriptor's package tree exists and the descriptor gate is green —
   unsatisfiable while a descriptor legitimately lands before its tree (the
   run plan's landing model), which child #11's own landing section affirms.
   The extension is fail-closed and state-explicit: a descriptor without its
   tree passes only while `check_repo.check_port_descriptors` reports it, and
   the gate test derives its expectation from each descriptor's disk state,
   reducing to `errors == []` once every tree, manifest, and entrypoint is
   present (the assembled-branch invariant, unchanged). No assertion was
   weakened for a descriptor whose tree exists.
2. **`.gitignore` classified as a byte copy.** The pin's package carries one
   (`__pycache__/`, `*.pyc`, `*.pyo`); `source_package_files` lists dotfiles,
   so it needs an explicit class. Byte copy is the conservative custody that
   keeps digest-verified derivation, and `provenance.dropped_reason` is a
   single shared string that must stay accurate for the paths genuinely
   dropped, so the redundant nested ignore file is carried rather than adding
   a second drop rationale.
3. **The child's load probe has a miswritten attribute.** `PortConfig`
   exposes the package name as `.name`; the probe text in child #11 reads
   `.package` and would raise `AttributeError` after a successful load on any
   descriptor, including the shipped UniFi one. The corrected probe
   (`print(c.name, ...)`) is what this unit ran; the load itself — the actual
   validity criterion — succeeds either way.
4. **`mutating_operations` encodes the audited verb list verbatim**, 24 CLI
   verbs plus the `_open_mapping_pr` internal path (`sdlc_manager.py:4664` at
   the pin — real `git worktree add`, `commit`, `push`, and `gh pr create`).
   Verbs that write locally rather than to GitHub (`issue prepare`, `config
   init`, `rollout update`) are not in the audited list and are therefore not
   in the descriptor; the audit, not this unit, owns that classification.
5. **All five package scripts are entrypoints; none excluded.** Rationale per
   script: `sdlc_manager.py` needs PyYAML at module scope (line 83 at the
   pin); `board_census.py` imports `sdlc_manager` from its own directory;
   `sync_template_docs.py` imports PyYAML (line 14); `check_pagination.py` is
   standard-library-only; `executor_profile_lint.py` runs only after its
   transform (module-scope `fleet_commons_shim` import, line 35).
6. **`assess_clients.py --package mission-control` cannot print the plan at
   this unit's head, by design.** The harness's `entrypoint_paths` refuses to
   plan invocation stages for entrypoints the package tree does not carry
   (the guard that stops a descriptor typo being graded as a package
   failure), and it fingerprints the shipped tree — there is no scratch-root
   override. With the tree legitimately absent until Lane A, the command
   raises the documented `AssessmentError` naming exactly the five declared
   entrypoints, which is the fail-closed behavior working as designed and
   evidence the descriptor's assessment block parsed and was consumed. The
   child's acceptance line "prints the ten-client plan and runs nothing"
   presupposes the assembled tree; it is the same interim-state class the
   landing model already names for `check_repo.py`. The declared entrypoints,
   package scripts, and skill units are each verified present in the pinned
   upstream inventory above, so the guard clears the moment Lane A lands; the
   plan print then runs as the child specifies. It was executed here and ran
   nothing, in the most literal sense available before the tree exists.
7. **Two repository-wide gate tests are red at this unit's head, and they are
   exactly the named package-completeness check.** The full suite (621 tests)
   fails two: `tests/test_check_repo.py::test_live_repository_passes_every_check`
   and
   `tests/test_unifi_readme.py::test_every_fenced_bash_command_is_runnable_from_the_repository_root`.
   Both fail on one error only — `port descriptor mission-control:
   package_root plugins/mission-control is not a directory` — the first
   directly, the second because the UniFi README documents
   `python3 scripts/check_repo.py` as a runnable command and the gate now
   exits non-zero. This is the interim state the contract's landing model
   names ("intermediate branch states may fail only the named
   package-completeness checks until the owning lane lands") and the unit
   instructions anticipate ("full `check_repo.py` green is NOT expected at
   this unit"). The child's verification block names `tests.test_port_config`
   — which is green — not the repo-wide gate modules, so these two are
   recorded red rather than remodeled; they go green with no edits the moment
   Lane A lands the tree.

## What follows this unit

- U3 (Lane A) syncs the tree from the pin, adds the two new single-shape
  transform rules and `normalize-skill-frontmatter` v1, and migrates this
  descriptor to schema 3 with per-path rule names — without revisiting any
  custody class this unit set (plan KTD7).
- The full `check_repo.py` gate and the sync `--check` reproduction move to
  the sync child and the assembled-branch gate, where the tree the descriptor
  names exists.
