---
title: Port the agent-launcher plugin from infiquetra-claude-plugins
type: feat
status: active
date: 2026-08-27
origin: infiquetra/infiquetra-agent-plugins#22
runbook: docs/runbooks/portable-plugin-port.md v1.1.0
backend: inline
---

# Port the agent-launcher plugin from infiquetra-claude-plugins

## Summary

Port the accepted `agent-launcher` plugin (shared single-session launch contract:
create via the `agents` wrapper, verify via Herdr, deliver a prompt, close only owned
sessions) from `infiquetra-claude-plugins` into a portable Agent Plugins package at
`plugins/agent-launcher`, governed by a new port descriptor `ports/agent-launcher.json`.
The launcher script lands as an unmodified upstream byte copy; the Claude-runtime
surfaces (plugin-cache discovery text, Claude manifest location, upstream test premises)
are superseded, relocated, or dropped per the custody model, and every adapter-specific
limitation is documented in the descriptor provenance and the portable docs.

## Problem Frame

The single-session launch contract was extracted, reviewed, and released upstream as
agent-launcher 1.0.0 (infiquetra-claude-plugins#777, merged at `28a881b3`, released
2026-08-25). Operator ruling G2 on infiquetra-claude-plugins#814 split the port out of
that issue: this repository is where the portable catalog carries it, tracked as issue #22.
The port adapts the shared contract for every client in this catalog rather than copying
Claude-specific behavior — the exact failure mode the source issue's pre-mortem names.

Carried-forward constraints from the issue (not revisited here): no Claude-side rework of
the accepted plugin; no new vendor or model registry (the live `agents` wrapper and Herdr
state remain authoritative); no Orchestrate behavior changes in either repository; stop if
the accepted plugin behavior cannot be represented without a vendor-specific hidden path.

## Grounded evidence (verified 2026-08-27)

- Start gate satisfied. infiquetra-claude-plugins#777 is CLOSED (2026-08-25T13:32Z);
  the source plugin shipped as 1.0.0. Evidence recorded on issue #22
  (comment 2026-08-27, "Port-start evidence record").
- Port source state. At upstream `origin/main` (`8269f84b` at record time),
  `git ls-tree -r --name-only origin/main -- plugins/agent-launcher/` lists exactly six
  paths: `.claude-plugin/plugin.json`, `CHANGELOG.md`, `README.md`,
  `skills/agent-launcher/SKILL.md`, `skills/agent-launcher/scripts/launcher.py`,
  `tests/test_launcher_contract.py`. The five non-test files are unchanged since the
  accepted release commit `28a881b3`; only the test file moved since (commits `844c133b`,
  `0d019597`, `48a15f05`), tracking Orchestrate-side changes that have no counterpart in
  this repository.
- Upstream suite green at the pin (runbook entry criterion). Executed 2026-08-27 from a
  disposable scratch clone checked out at `8269f84b`: `python3 -m pytest
  plugins/agent-launcher/tests -q` — 36 passed. The authoritative upstream checkout stayed
  at `origin/main` with a clean tracked tree before and after. U1 repeats this check at the
  actual sync pin if the pin moves.
- Contract shape. `launcher.py` (1387 lines) is pure standard library, self-contained
  (no imports beyond stdlib), and vendor-gated: the Claude account-verification block
  (`check_unit_account`, transcript-root and statusline evidence) runs only when
  `vendor == "claude"`; the vendor flag/permission/notes tables are the shared contract's
  own tables, resolved against the live wrapper every run (`roster()`), which is exactly
  the "no private registry" boundary the issue carries. `VENDOR_FLAGS` names exactly seven
  vendors: claude, codex, grok, muse, agy, qwen, opencode.
- This repository's baseline. `main` at `f981ed4`: `python3 scripts/check_repo.py`
  passes; `python3 -m unittest discover -s tests` — 755 tests OK;
  `python3 -m pytest plugins/*/tests -q` — 551 passed, 192 subtests passed.
- Repository tooling. CI (`.github/workflows/ci.yml`) runs `check_repo.py` +
  `unittest discover -s tests` + `git diff --check` (stdlib-only hermetic job) and
  `pytest plugins/*/tests` on Python 3.12 (plugin-tests job). The issue's `uv run pytest`
  verification block did not apply (no pyproject.toml in this repository); the corrected
  check set is recorded on the issue and the issue body itself was updated to it on
  2026-08-27. Merge methods: squash and rebase allowed, merge commits disabled, branch
  auto-delete on merge.
- Review controllers. This run's Doc Review and Code Review controllers are the
  existing herdr sessions in the "Improve Agent Plugins" workspace (tabs `Doc Review`
  and `Code Review`); they run the installed Saga `/doc-review` and `/code-review`
  processes. No substitute reviewers are created. Phase 4 review is the installed
  `/code-review` controller, bounded by its three-cycle ceiling.

## Requirements

R1. Honor the start gate before implementation: issue infiquetra-claude-plugins#777
CLOSED (verified above; evidence comment on issue #22).

R2. `ports/agent-launcher.json` exists, is non-empty, validates at schema version 3
(`scripts/port_config.py`), and documents the adapter-specific limitations in its
provenance notes and in the ported package's documentation.

R3. `plugins/agent-launcher/` exists as a derived package byte-faithful to the pinned
upstream commit: `python3 scripts/sync_vendor_source.py --package agent-launcher --source
<checkout> --commit <pin> --check` exits 0, and `PROVENANCE.json` digests match on every
byte-copied and transformed path.

R4. The shared launch contract is exercised in this repository: the ported package
carries a target-owned functional suite under `plugins/agent-launcher/tests/` covering the
portable half of the upstream contract tests, green under `python3 -m pytest
plugins/agent-launcher/tests`.

R5. The repository check set is green with the port included: `check_repo.py`,
`python3 -m unittest discover -s tests`, `python3 -m pytest plugins/*/tests -q`, and
`git diff --check` — the exact CI commands. Run-wide gate, verified at every unit
boundary and on the PR head.

R6. The supported-client matrix is committed under `docs/evidence/` as one current,
fingerprint-bound record (bound to `(file_count, tree_sha256)`), validated by
`scripts/check_compatibility_matrix.py`; blocked stages carry honest reasons, never blank
ones. Exactly one record per package is `current` at any time — unifi and mission-control
keep their own current matrices; this port adds agent-launcher's: an accepted repair that
moves the fingerprint freezes the successor tree, re-runs only the evidence whose binding
moved, and marks the replaced record superseded with its successor and reason — it is
never edited or renumbered. This is the runbook's evidence loop, not a lifetime one-run
promise.

R7. Packaging smoke coverage exists for the generated package: relocated Claude
manifest identity/version agreement, portable manifest validity, and the no-marketplace
scope lock each have a test.

R8. The shipping PR updates this repository's release/metadata surfaces per its
conventions: root `README.md` (Status narrative + Packages table + record of work),
`llms.txt` Packages section, `docs/README.md` index, and the Python-floor declaration
sites when the new README declares the floor.

R9. Non-goals hold: no upstream rework (a needed byte change is an upstream filing,
never a downstream patch), no new vendor or model registry, no Orchestrate changes, no
marketplace entry, no live agent sessions launched by unattended verification. Run-wide.

R10. The catalog floor `python>=3.12` is honored and declared consistently
(`tests/test_python_floor.py` owns the floor; any new declaration site is registered
there in the same commit).

R11. Runbook v1.1.0 phases are followed and its version is recorded in this plan and
the saga tick; its stop conditions are this run's stop conditions.

## Key Technical Decisions

KTD1. `launcher.py` is an upstream byte copy, Claude account block included. The
contract is stdlib-only and vendor-gated; the Claude account-verification paths are
explicit, documented behavior for `vendor == "claude"`, not a vendor-specific hidden
path. Modifying the bytes would violate the custody rule that a portable copy is a
derived artifact ("where the portable tree would need a different byte, the repair is
authored upstream first" — `ports/unifi.json` provenance), and the issue forbids
Claude-side rework in this run. The limitations are documented instead (KTD8).

KTD2. Upstream `SKILL.md` and `README.md` are superseded by target-owned portable
docs; there are no client byte copies. The upstream SKILL.md's quickstart resolves the
script through `$CLAUDE_PLUGIN_ROOT` with a fallback ladder into
`~/.claude/plugins/cache/` — Claude-runtime discovery that would let a non-Claude client
run the launcher from a Claude plugin install instead of the assessed package. Copying
those bytes is the exact "copy Claude-specific behavior" failure the issue's pre-mortem
names. The portable SKILL.md carries the same contract, stop conditions, and boundaries
with package-root-relative script discovery; the portable README documents the derived
package (`LEARNINGS.md`: "A byte-copied README describes the source package, not the
derived one"). Mission-control superseded its README for the identical reason. The
`com.infiquetra.claude/` adapter directory therefore holds only the relocated Claude
manifest, mirroring how both existing ports carry it.

KTD3. The upstream test suite is dropped with a recorded reason; the portable suite
is target-owned under `plugins/agent-launcher/tests/`. Five upstream tests assert
premises of `infiquetra-claude-plugins` itself (Orchestrate ingests the launcher,
Orchestrate's plugin.json declares the dependency array, the repo-root marketplace) that
have no counterpart here, and the file resolves the repo root as `parents[3]` — a shape
`LEARNINGS.md` explicitly forbids repeating ("Package-internal asset paths must avoid
assuming fixed ancestor repository depth"). Precedent: mission-control dropped
`tests/test_prompt_alignment.py` as a whole-upstream drift guard whose premises cannot
cross the port boundary (`DECISIONS.md`, "A whole-repository drift guard is dropped…").
The portable half of the contract tests is re-authored against the package layout,
resolving the launcher via `parents[1]`.

KTD4. The pin is upstream `origin/main` HEAD at synchronization time. The five
non-test source files are unchanged since the accepted release `28a881b3`; the only
later movement is the dropped test file. The sync tool's `--commit` rule is "the
corrected revision, never an earlier one" (`scripts/sync_vendor_source.py` CLI help),
so the current head is pinned, never an earlier revision; the exact SHA lands in
`PROVENANCE.json` (`source_commit`).

KTD5. Assessment block: entrypoint inside the single skill unit; honest empty
credential surface; mutating verbs named. `entrypoints:
["skills/agent-launcher/scripts/launcher.py"]` sits inside `skill_units:
["skills/agent-launcher"]`, so all four skill-scoped clients can deliver it
(`scripts/assess_clients.py` blocks invocation in advance only for entrypoints outside
every unit). `mutating_operations: ["launch", "close"]` scoped by `package_scripts:
["launcher.py"]` lets the harness safety rule (`scripts/check_compatibility_matrix.py`
`command_safety_problems`) refuse the session-creating and session-closing verbs during
assessment; the harness invokes entrypoints as `--help` only. `credential_prefixes` is
empty and named in `declared_none`: the launcher reads no credentials (its
`CLAUDE_PERSONAL_PROJECTS`/`CLAUDE_COMPANY_PROJECTS` reads are transcript *locations*,
not secrets) — stated visibly rather than defaulted away.

KTD6. Portable manifest version is `1.0.0`, equal to the upstream `source_version`
at the pin. Version strings in this catalog are derivation claims, not release counters
(`DECISIONS.md`, "A slice expansion at an unchanged pin…").

KTD7. No marketplace entry; the absence is locked by a test. The repo-root
marketplace lists only `voice`; `QUEUED.md` (P1) withholds catalog distribution pending
an operator decision, and mission-control's rule audit already asserts its own absence
(`tests/test_mission_control_rule_audit.py`, structural-premises test). The packaging
smoke test asserts `agent-launcher` is not listed, locking this scope decision.

KTD8. Adapter-specific limitations are documented in three places. The descriptor
`provenance.notes` (carried verbatim into `PROVENANCE.json`), the portable README's
limitations section, and the portable SKILL.md each state: (a) account verification
applies only to `vendor == "claude"` and reads Claude transcript roots/statusline
evidence; (b) the package requires the live `agents` wrapper and Herdr on the machine —
no wrapper, no launch (a stop, not a fallback); (c) vendor model/effort control follows
the live wrapper and the contract's tables, never a roster shipped in this package;
(d) OpenCode variant selection and qwen's typing-limit file handover are interactive
behaviors documented in the contract, unchanged by the port.

KTD9. One branch, one squash-merged PR; the plan rides as the branch's first
artifact. An unattended single-issue run gains no review value from a separate docs PR;
the squash merge keeps the merged history a single unit. Branch `port/agent-launcher`
off `main` (`f981ed4`). The project-board Status field moves at each real phase
boundary; GitHub issue comments stay one closeout comment at merge, never per-step
chatter.

KTD10. Evidence is content-bound and kept current, not run-once. Every matrix record
binds to `(file_count, tree_sha256)` from `scripts/check_compatibility_matrix.py
--print-fingerprint agent-launcher` on the frozen tree, and mutation proofs bind to the
guarded blobs' digests, never to commit ids. Exactly one record per package is
`current`: the first freeze captures agent-launcher's; an accepted repair that moves the
fingerprint (Phase 4, installed `/code-review` controller, three-cycle ceiling) freezes
the successor, re-runs only the evidence whose binding moved, and supersedes the
replaced record with successor and reason (`DECISIONS.md`, "A re-synchronization does
not renumber the evidence it invalidates"; the eight superseded unifi matrices are the
precedent). Repairs that touch only docs or repo metadata outside the package do not
move the fingerprint and do not re-run evidence.

## Implementation Units

Serial dependency chain U1 → U2 → U3 → U4 → U5. Every unit lands on branch
`port/agent-launcher`; `PROVENANCE.json` and the package fingerprint move until U4
freezes the tree, so no unit runs in parallel. Backend for every unit: inline.
R1 is evidenced above; R5 and R9 are run-wide gates held at every boundary.

### U1. Port descriptor, synchronized tree, and portable core surface

One commit that lands `ports/agent-launcher.json`, the synchronized upstream bytes, and
the target-owned core surface, leaving `check_repo.py` green.

**Goal:** the descriptor and the complete package tree exist together and validate, so
every later unit builds on a byte-faithful derived package.

**Requirements:** R2, R3.

**Depends on:** none (first unit).

**Approach:** complete the runbook Phase-0 entry criteria first: the upstream suite is
green at the pin (already executed 2026-08-27 from a disposable scratch clone at
`8269f84b` — 36 passed, authoritative checkout untouched; repeat at the actual sync pin
only if the pin moved), the floor interpreter exists by explicit path
(`/opt/homebrew/bin/python3.12`, CPython 3.12.13), non-goals are written (Scope
Boundaries), and merge methods were read (squash/rebase). Then write the descriptor and
the target-owned surface before the writing sync, because sync records target-owned
paths into `PROVENANCE.json` at write time and `--check` rebuilds the expected manifest
from disk: descriptor + target-owned first, sync second, `--check` third.

**Patterns reused:** the `ports/unifi.json` and `ports/mission-control.json` descriptor
prose conventions; mission-control's README supersession; the ports/README.md "Adding a
package" command sequence.

**Files:** `ports/agent-launcher.json` (new); `plugins/agent-launcher/plugin.json`
(target-owned portable manifest: `$schema`
`https://agent-plugins.org/schemas/1.0.0/plugin.schema.json`, name `agent-launcher`,
version `1.0.0`, description naming the derivation); `plugins/agent-launcher/README.md`
(target-owned, supersedes upstream); `plugins/agent-launcher/skills/agent-launcher/SKILL.md`
(target-owned portable skill, frontmatter `name: agent-launcher` + `description` only,
body carries the contract with package-root-relative script discovery and KTD8
limitations); `plugins/agent-launcher/.gitignore` (the ported-package convention:
`__pycache__/`, `*.pyc`, `*.pyo`); plus synchronized output: `CHANGELOG.md`,
`skills/agent-launcher/scripts/launcher.py`, `com.infiquetra.claude/plugin.json`,
`PROVENANCE.json`.

**Descriptor custody (schema 3):** `byte_copies`: `CHANGELOG.md`,
`skills/agent-launcher/scripts/launcher.py`. `superseded_by_target_owned`: `README.md`,
`skills/agent-launcher/SKILL.md`. `dropped_from_source`:
`tests/test_launcher_contract.py` with `provenance.dropped_reason` recording that the
suite's premises (Orchestrate ingestion, Claude marketplace dependency declarations,
`parents[3]` repo layout) cannot cross the port boundary and the portable suite replaces
it. `source.manifest_path: .claude-plugin/plugin.json` + `client_extension_dir:
com.infiquetra.claude` (relocate-claude-manifest is applied unconditionally to the
manifest; it is never a selectable rule). No `entrypoint_transforms` (launcher.py needs
none; SKILL.md carries no `when_to_use`, so `normalize-skill-frontmatter` would be a
no-op and byte-copy is not its honest class — the supersession handles it). Assessment
block per KTD5. Provenance notes per KTD8 plus the custody rationale notes.

**Mechanism (ordered):** (1) write `ports/agent-launcher.json`; (2) write the
target-owned surface (`plugin.json`, `README.md`, portable `SKILL.md`, `.gitignore`);
(3) `python3 scripts/sync_vendor_source.py --package agent-launcher --source
<infiquetra-claude-plugins checkout> --commit <origin/main HEAD>` — the checkout must be
clean per `git status --porcelain --untracked-files=no`; (4) re-run the identical command
with `--check` (exit 0); (5) `python3 scripts/check_repo.py` (exit 0).

**Test scenarios:** generic coverage lands automatically — `check_repo.py` validates the
descriptor, package, manifest, and entrypoint presence; `tests/test_client_entrypoints.py`
iterates every descriptor with a `PROVENANCE.json` and runs `launcher.py --help`
credential-free (its PROVENANCE gate includes this package once U1 lands). No new test
file in U1 — the dedicated guards arrive in U2/U3 against the bytes U1 lands.

**Verification:** `python3 scripts/check_repo.py` exits 0; `sync --check` exits 0;
`python3 -m unittest discover -s tests` green. The package has no `tests/` directory yet;
CI's `plugins/*/tests` glob omits a missing directory (fleet-core precedent), and
`python3 -m pytest plugins/agent-launcher/tests` becomes a gate only in U2.

### U2. Target-owned functional suite inside the package

The portable half of the upstream contract tests, re-authored against the package
layout, plus documentation guards for the portable skill and README.

**Goal:** the shared launch contract is exercised from the portable layout, and the
target-owned docs are guarded by class-based tests.

**Requirements:** R4.

**Depends on:** U1.

**Approach:** adapt every portable upstream test, resolving all paths from the test
file's package root (`Path(__file__).resolve().parents[1]`), never a fixed ancestor
depth; upstream test names are cited in the module docstring so the adaptation is
auditable against `test_launcher_contract.py` at the pin. Doc guards are class-based
(every member of the input class in its vulnerable shape), not derived from one failing
example.

**Patterns reused:** the `MutationProofBindingTest` guard style lands its proofs in U3;
package-internal resolution via `parents[1]` (`LEARNINGS.md`, the Cursor failure).

**Files:** `plugins/agent-launcher/tests/__init__.py`;
`plugins/agent-launcher/tests/test_launcher_contract.py` (adapted subset: background-flag
ordering before the vendor token across all seven contract vendors; `--dry-run` in the
launcher position; CLI `argv` subprocess with a fake `agents` wrapper on PATH;
`--skip-preview` refusal; malformed-receipt and nonzero-wrapper stops; timeout-as-result;
prompt-delivery failure records `PROMPT_UNDELIVERED` + warning; the close-ownership
quartet (no receipt tab_id, mismatched receipt, owned closes exactly the receipt tab,
preexisting tab is not owned); cwd mismatch on a preexisting tab does not close it;
ownership is defined as the receipt tab_id absent from the pre-launch snapshot;
`confirm_preview` cwd/workspace mismatch; preflight receipt separates
`confirmed_against_herdr` from `requested_only`; cwd-mismatch closes only owned sessions;
kind mismatch stops before prompt; path-separator/traversal refusal in task names
(including the `pane_text` long-task path); failed launch persists `tab_id` for close;
CLI exits nonzero on undelivered prompt); `plugins/agent-launcher/tests/test_portable_docs.py`
(class-based guards: the portable SKILL.md resolves the script package-root-relative and
never names `~/.claude/plugins/cache` or `$CLAUDE_PLUGIN_ROOT`; it carries the verbatim
stop conditions and the herdr dependency note; its cleanup example redirects the receipt
(`> receipt.json` with `close --receipt-json receipt.json`, never the
`close --tab-id <tab_id> --receipt-json <receipt.json>` form); no duplicate herdr skill
directory ships beside it; the README opens as a portable-package document and states the
KTD8 limitations).

**Test scenarios:** all of the above live in the two new files and run under `python3 -m
pytest plugins/agent-launcher/tests -q` (CI's plugin-tests job picks the directory up
via its glob). Mutation-sensitivity of the doc guards is proven in U3, not here.

**Verification:** `python3 -m pytest plugins/agent-launcher/tests -q` green on the
Python floor interpreter and on the repo default; full repo suite still green.

### U3. Repository-root guards: packaging smoke, descriptor shape, mutation proofs

Repo-level tests that lock the packaging shape and prove the U2 guards detect mutation.

**Goal:** the packaging invariants are pinned by repo-root tests, and every guard this
port authors is mutation-proven against the committed blobs.

**Requirements:** R7.

**Depends on:** U2.

**Approach:** unittest stdlib-only tests at the repo root (mission-control splits
repo-level rule audits from package functional suites the same way); mutation proofs
mutate a temporary copy of each guarded blob and assert the guard fails on mutated bytes
and passes on committed bytes, bound by sha256.

**Patterns reused:** mission-control's structural-premises absence assertion; the unifi
not-blocked geometry test; the `MutationProofBindingTest` pattern.

**Files:** `tests/test_agent_launcher_packaging.py` (unittest, stdlib-only: the relocated
`com.infiquetra.claude/plugin.json` parses and its `name`/`version` agree with
`PROVENANCE.json` `source_version`; the portable `plugin.json` carries the Agent Plugins
`$schema` and non-empty `name`/`version`/`description` with the same version; the
repo-root marketplace exists but does not list `agent-launcher` — KTD7's lock, on the
mission-control absence-assertion model; no `hooks/`/`agents/`/`commands/` convention
directory sits at the portable root); `tests/test_assess_clients.py` gains a bespoke
shape test loading `port_config.load("agent-launcher", ROOT)` asserting the skill-scoped
plans are not blocked in advance (entrypoint inside the unit — the pattern is unifi's
`test_skill_scoped_plan_with_all_deliverable_entrypoints_is_not_blocked` at
`tests/test_assess_clients.py:1449`; the mission-control blocked-in-advance test at line
1421 is the negative control this package must not resemble);
`tests/test_agent_launcher_rule_audit.py` (unittest, stdlib-only: the custody table
classifies exactly the six pinned upstream paths once each; `PROVENANCE.json`
`removed_from_source` names the dropped test file; the U2 doc guards' mutation proofs,
bound by digest to the committed blobs).

**Test scenarios:** the three files above; run under `python3 -m unittest discover -s
tests`.

**Verification:** full unittest suite green; `python3 scripts/check_repo.py` green;
`git diff --check` clean.

### U4. Freeze and Phase-3 evidence: fingerprint, ten-client matrix, readback

Freeze the candidate tree and gather the runbook Phase-3 evidence bound to it, keeping
exactly one agent-launcher matrix record `current` (R6).

**Goal:** the shipped tree carries one current fingerprint-bound matrix and one
readback for this package, both validated, and the floor is verified from staged bytes.

**Requirements:** R6.

**Depends on:** U3.

**Approach:** evidence binds to content, never to commit ids; a later accepted repair
that moves `(file_count, tree_sha256)` supersedes this record and re-runs only the moved
evidence (KTD10), inside the installed `/code-review` controller's three-cycle ceiling.

**Patterns reused:** the mission-control matrix document shape
(`docs/evidence/2026-08-25-mission-control-compatibility-matrix.md`); the runbook
Phase-3 checklist; the floor-by-explicit-path rule (`/opt/homebrew/bin/python3.12`,
CPython 3.12.13 — launcher.py is stdlib-only, so the venv carries no third-party
dependencies).

**Steps:** (1) Stage everything; verify floor from staged bytes — extract the staged
`launcher.py` blob to a temp path and run `--help` under the explicit Python 3.12
interpreter, per runbook Phase 3. (2)
`python3 scripts/check_compatibility_matrix.py --print-fingerprint agent-launcher` —
record `(file_count, tree_sha256)`. (3) `python3 scripts/assess_clients.py --package
agent-launcher` — print the plan, confirm every stage argv and the statically-blocked
rows. (4) `python3 scripts/assess_clients.py --package agent-launcher --execute
--python <explicit python3.12 venv interpreter> --workspace <scratch dir> [--real-binary
<name>=<path> per the runbook quirk table] --out <record path>` — one run directory per
attempt, fresh each time, per-client package copies, credential-stripped environments;
the harness invokes entrypoints as `--help` only and the safety rule blocks `launch`/
`close` (KTD5), so no live agent session is created by this run. (5) Author
`docs/evidence/2026-08-27-agent-launcher-compatibility-matrix.md`: first fenced json
block is the record (with `assessed_on`, per-client `version`/`reason` filled from the
private transcript; blank reasons are refused by the validator, so unfinished rows stay
honest), `<!-- matrix-status: current -->` directive, prose summary, inert values only
(`docs/public-safe-summary.md`). (6) One readback evidence document beside it
(`2026-08-27-agent-launcher-post-activation-readback.md`, precedent naming). (7)
`python3 scripts/check_compatibility_matrix.py` (no arguments) validates every matrix
document including the new one.

**Test scenarios:** no new test file — the no-argument validator run and the committed
suite already cover the record (`tests/test_check_compatibility_matrix.py`'s discovery
test uses `assertIn`, so an added matrix does not break it); the evidence documents are
the artifacts.

**Verification:** validator exits 0; the record's `package` block equals the printed
fingerprint; the private transcript stays owner-only and uncommitted; suite green.

### U5. Closeout: metadata surfaces, journal, board evidence

Update every surface that enumerates packages and record the decisions.

**Goal:** the catalog's metadata surfaces enumerate the new package, the journal
carries the port's decisions, and the board/issue closeout happens exactly once.

**Requirements:** R8, R10, R11.

**Depends on:** U4.

**Approach:** update each enumerating surface in one commit; the journal entry mirrors
this plan's KTDs; the project-board Status field may move at phase boundaries, while the
GitHub issue receives one closeout comment at merge (KTD9).

**Patterns reused:** mission-control's U9 closeout (README Status narrative + package
table, `llms.txt` Packages bullet, docs index entry).

**Files:** `README.md` (Status narrative + Packages table row for
`plugins/agent-launcher/` with the upstream pin, Key facts, record-of-work list);
`llms.txt` (one Packages bullet for the new README); `docs/README.md` (index entries for
this plan and the matrix evidence); `tests/test_python_floor.py` `DECLARATION_SITES`
gains `plugins/agent-launcher/README.md` if that README declares `python>=3.12` (it
does — same commit, floor owned by that test); `docs/engineering-journal/DECISIONS.md`
(port entry mirroring KTD1–KTD10: byte-copy custody with the Claude account block,
SKILL/README supersession, test custody drop, assessment safety declarations, no
marketplace, evidence bindings; `LEARNINGS.md` only if the run produced a genuinely new
lesson); saga tick with destination, decisions, and runbook version.

**Test scenarios:** `tests/test_python_floor.py` green with the new declaration site;
`check_repo.py` markdown-link check green across the updated docs; no new bespoke test
file — the floor test and the generic validators are the guards.

**Verification:** full check set green on the exact frozen-plus-closeout commit
(`check_repo.py`, unittest discover, plugin pytest, `git diff --check`); board Status
moves to reflect the merge; one closeout comment on the issue.

## Scope Boundaries

**Out of scope (non-goals):**

- No Claude-side rework of the accepted plugin; a needed byte change is an upstream
  filing and a repin, never a downstream patch (issue non-goal; runbook anti-pattern).
- No new vendor or model registry; `launcher.py`'s tables and live-wrapper probing are
  carried unchanged (issue non-goal).
- No Orchestrate behavior changes in either repository (issue non-goal).
- No marketplace entry for `agent-launcher` — catalog distribution is withheld pending an
  operator decision (`QUEUED.md` P1); KTD7 locks the absence by test.
- No live agent sessions launched by unattended verification; the assessment invokes
  entrypoints as `--help` and blocks the mutating verbs (KTD5, R9).
- No Fleet Core bundle: `launcher.py` imports nothing outside stdlib, so no
  `fleet-bundle.json`, no `_bundled/` outputs (verified by reading the imports, per
  `LEARNINGS.md` "A plugin's tracked file list does not reveal what it needs to run").
- No per-client remediation follow-ups from the matrix run (`QUEUED.md` P1).

**Deferred to Follow-Up Work:**

- Marketplace distribution of ported packages, if the operator later authorizes catalog
  publication (separate decision, separate work).
- Upstream filings for anything the port surfaces in the accepted contract (none known
  at plan time).
- The portable package documents its dependency on the canonical `herdr` skill; this
  repository does not own Herdr definitions, so no dependency packaging ships here.

## Risks and Mitigations

- Ten-client environment gaps on this machine. Some client binaries may be absent or
  wrapper-shimmed. Mitigation: blocked stages carry honest reasons (the validator refuses
  blank ones); operator-supplied `--real-binary` overrides per the runbook quirk table;
  the matrix commits with works/blocked rows as assessed — precedent in the existing
  unifi and mission-control matrices.
- Python 3.12 floor interpreter availability locally. CI pins 3.12; the local
  default `python3` is newer (3.14). Mitigation: the explicit interpreter is already
  verified present (`/opt/homebrew/bin/python3.12`, CPython 3.12.13); a missing floor
  interpreter would stop the evidence phase for the operator rather than silently using a
  newer one (`LEARNINGS.md`: "A default interpreter is not evidence for a declared
  floor").
- Pin drift between plan and sync. Upstream may move. Mitigation: KTD4 pins
  `origin/main` HEAD at sync time; `PROVENANCE.json` records the exact SHA; U1 repeats
  the scratch-clone upstream-suite check if the pin moved; any upstream movement after
  the freeze is a supersession event (new matrix record), never an in-place edit.
- Accepted Code Review repairs that move the fingerprint. Mitigation: KTD10/R6 — the
  superseded record stays with its reason, the moved evidence re-runs once against the
  successor tree, inside the three-cycle ceiling.
- Adapted tests drift from the upstream contract. Mitigation: launcher.py is a byte
  copy, so contract behavior cannot drift; the adapted suite cites upstream test names;
  a contract change need is an upstream filing and repin, which stops this run for the
  operator.
- Untracked local directories. `.serena/` (user-owned) and `.qwen/` (session) remain
  untouched; nothing broad-stages (`git add` names paths explicitly).

## Success Metrics

- Issue #22 acceptance criteria all checked: start gate honored (done, evidenced); repo
  check set green with the ported suite included; `ports/agent-launcher.json` present,
  non-empty, limitations documented; shipping PR updates the metadata surfaces.
- One `current` fingerprint-bound matrix and one readback committed under
  `docs/evidence/`, supersession used (never renumbering) if a repair moved the tree;
  validator clean.
- Merged via squash on `main` with CI green on the merged head; board card Done.
