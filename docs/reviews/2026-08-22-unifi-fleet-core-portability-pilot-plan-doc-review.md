# Saga document review — UniFi and portable Fleet Core portability pilot

This review covers the implementation plan on pull request (PR) #2 in `infiquetra-agent-plugins`, where readiness matters because the plan would coordinate source, release, deployment, and compatibility work across three repositories.

## Applied fixes

No fixes were applied. The operator required the plan, source code, external systems, other repositories, and Saga state to remain read-only; this review artifact is the only created file.

## Readiness summary

**Verdict: NOT READY — implementation is blocked by ten Saga priority P1 findings.** Saga priority P1 means a core decision, mapping, default, or gate is missing or wrong, so an implementer would have to invent behavior or exceed an authority boundary. Saga priority P2 means the document can probably drive work but would create meaningful rework, ambiguity, or review risk.

The plan correctly preserves the central operator decisions about repairing the authoritative Claude source before synchronization, porting only the `retry_backoff` Fleet Core module, generating the consumer bundle, keeping the site profile optional, assessing all ten installed clients without requiring ten passes, and pausing before any client-specific remediation. Those decisions are not enough to approve the document because their source-custody, execution, profile, release, and evidence mechanics contradict one another or remain incomplete.

## Review-result contract

The review is tied to the exact PR head and the installed Saga contract used for this pass.

| field | value |
|---|---|
| target path | `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md` |
| classification | Plan document; Saga readiness-skeptic pass |
| reviewed revision | PR #2 head `43b4cc833381cd6da3593de7808cc2ab7dcb43bc`; base `9a2c6d7e2497d7bbdfb801cf63ef83edb4176ea8` |
| PR | [infiquetra-agent-plugins PR #2](https://github.com/infiquetra/infiquetra-agent-plugins/pull/2) |
| Saga preflight | `saga` version `0.83.0+codex.20260811103502` is installed and enabled; its document-review skill and formatting contract match the current marketplace checkout and upstream commit `e85d4150aad9e7e17bce03a3387b2588ea8fd9fa` |
| blocked | yes |
| findings | 10 open P1 findings; 2 open P2 findings; no P0 or P3 findings |
| applied fixes | none |
| override rationale | none |
| review artifact path | `docs/reviews/2026-08-22-unifi-fleet-core-portability-pilot-plan-doc-review.md` |
| linked plan state | The ignored `.claude/saga/` state was read for consistency and not changed |

## Remaining findings by priority

The blocking findings concern decisions and gates, not prose polish.

| finding | priority | status | plain-language finding |
|---|---|---|---|
| D1 | P1 | open | The plan records the per-unit Saga backend as `inline` and later says the backend is undecided; it also omits the settled outer-controller ownership by Orchestrate through Herdr. |
| D2 | P1 | open | The dependency graph spans three repositories, but the current Orchestrate run model owns one repository and has no per-unit repository field; the plan does not define the required multi-run handoffs. |
| D3 | P1 | open | The UniFi copy is declared fully derived with no intentional divergence, while the plan adds target-owned files and rewrites skill frontmatter only after synchronization. |
| D4 | P1 | open | The plan makes Fleet Core a first-class portable source without deciding custody of `retry_backoff` or specifying the promised version, provenance, release, and compatibility surfaces. |
| D5 | P1 | open | The generated bundle has no declared-module manifest or closed digest contract, so the build and stale-bundle validator require invention. |
| D6 | P1 | open | The optional site-profile and discovery design lacks an executable storage, format, dependency, setup-entrypoint, and no-inference contract across the target and Claude repositories. |
| D7 | P1 | open | The upstream activation unit cannot yet prove the no-capability-gap claim because its release surfaces, pre-activation staging path, fresh-session readback, and rollback trigger are unspecified. |
| D8 | P1 | open | The ten-client gate can pass with ten status rows even when the four mandatory smoke stages were not each attempted or explicitly blocked with evidence. |
| D9 | P1 | open | The public transition evidence can capture private topology or controller output because the plan states exclusion but defines no sanitization or evidence schema. |
| D12 | P1 | open | The upstream documentation-repair unit promises new regression assertions but owns no test file and leaves several corrected surfaces outside its stated checks. |
| D10 | P2 | open | The plan's count of sixteen unported Fleet Core modules does not match the authoritative source tree. |
| D11 | P2 | open | The plan and PR body say four repositories are touched, but the ownership map names only three distinct repositories. |

### D1 — P1 — The execution backend is settled, but the plan says it is open

The intended ownership has two layers: Orchestrate is the outer controller and uses Herdr to dispatch and monitor work, while `backend: inline` is the Saga backend inside every dispatched unit so no unit starts nested orchestration.

| aspect | evidence |
|---|---|
| contradiction | The plan records `backend: inline` at `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:1-8`, then says the execution backend and routing destination are unchosen at `:528-534`. |
| source truth | The architecture assigns session execution to Herdr at `docs/cross-vendor-plugin-architecture-brief.md:61-69` and says Orchestrate delegates execution to Herdr at `:106-113`. The authoritative Orchestrate contract says the plan always carries `backend: inline` because a dispatched unit must not nest another workflow at [`plugins/orchestrate/commands/orchestrate.md:119-123`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/995a475/plugins/orchestrate/commands/orchestrate.md#L119-L123), and the run model repeats that rule at [`orchestrate.py:435-447`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/995a475/plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py#L435-L447). |
| required correction | Remove the stale open question and add an execution-ownership section naming Orchestrate-through-Herdr as the outer controller and `inline` as the per-dispatched-unit Saga backend. Clarify that `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:502` means Saga and Team Execution source are unchanged, not that the approved controller is unused. |

This is material because a literal worker can otherwise stop for an already-answered question, run everything in the main session, or create the nested orchestration the settled backend avoids.

### D2 — P1 — One Orchestrate run cannot encode this three-repository graph

The plan needs an explicit multi-run or handoff topology before Orchestrate can own its dependency graph.

| aspect | evidence |
|---|---|
| plan shape | The plan declares twelve units across `infiquetra-agent-plugins`, `infiquetra-claude-plugins`, and `home-lab`, with evidence returning to the target repository at `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:190-215` and `:457-466`. |
| controller limit | Current Orchestrate describes one driven repository and one worktree per unit at [`plugins/orchestrate/README.md:1-18`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/995a475/plugins/orchestrate/README.md#L1-L18). Unit ownership paths are repository-relative at [`orchestrate.py:369-373`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/995a475/plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py#L369-L373), and the controller resolves one repository root from its current checkout at [`orchestrate.py:1078-1091`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/995a475/plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py#L1078-L1091). |
| required correction | Define the approved outer topology: which repository owns each Orchestrate run, which receipt releases each cross-repository dependency, where the controller pauses for authority, and how the target-repository run resumes at implementation unit U10 after the Claude and home-lab work lands. |

This is material because placing an outside-repository unit in the current run would either launch it in the wrong worktree or require ambient writes beyond that unit's declared authority.

### D3 — P1 — The UniFi derivation rule conflicts with the planned output

The plan does not distinguish byte-derived upstream files, deterministic transformations, and new portable files owned only by this repository.

| aspect | evidence |
|---|---|
| no-divergence rule | Requirements R1 through R4 say the portable copy is derived, digest-verified, and never intentionally different from the authoritative source at `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:28-36`; Key Technical Decisions (KTDs) 1 and 2-prime repeat that rule at `:104-110`. |
| contradictory output | Implementation units U4 and U5 author new files directly under `plugins/unifi/` at `:277-315`. Implementation unit U10 then copies `plugins/unifi/skills/**` and removes `triggers` and `script` from frontmatter downstream at `:397-415`, even though the authoritative skill files still carry those fields at [`unifi-network/SKILL.md:1-17`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/995a475/plugins/unifi/skills/unifi-network/SKILL.md#L1-L17) and [`unifi-protect/SKILL.md:1-16`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/995a475/plugins/unifi/skills/unifi-protect/SKILL.md#L1-L16). |
| required correction | Classify every target path as an upstream byte copy, a versioned deterministic transform, or target-owned portable source. Either repair the frontmatter upstream before synchronization or define transform provenance with source digest, output digest, and transform version; also define how synchronization preserves target-owned U4 and U5 files instead of overwriting or silently omitting them. |

This is material because two reasonable synchronizers can both follow the prose and produce different trees, while only one can preserve the site-profile work and the no-divergence decision.

### D4 — P1 — Fleet Core custody and lifecycle are not decided

Calling Fleet Core a first-class portable source changes authority, but the plan never says whether authority for `retry_backoff` moves or remains in the Claude repository.

| aspect | evidence |
|---|---|
| promised lifecycle | Requirement R16 promises Fleet Core its own tests, releases, versioning, provenance, and compatibility contract at `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:64-76`. Implementation unit U2 lists only `plugin.json`, `DEFERRED.md`, `README.md`, the module, and its test at `:237-255`; the assembled tree likewise has no provenance or changelog at `:184-188`. |
| current authority | This repository says existing vendor repositories remain authoritative until a pilot and later custody decision prove otherwise at `README.md:11-15` and `docs/engineering-journal/DECISIONS.md:53-70`. The source Fleet Core manifest is version `0.25.0` at [`plugins/fleet-core/.claude-plugin/plugin.json:1-4`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/995a475/plugins/fleet-core/.claude-plugin/plugin.json#L1-L4), and the module documents its Fleet Core compatibility promise at [`retry_backoff.py:1-18`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/995a475/plugins/fleet-core/scripts/fleet_commons/retry_backoff.py#L1-L18). |
| required correction | Record who owns future `retry_backoff` edits, what initial portable version and provenance are derived from Fleet Core `0.25.0`, which files form its release surface, and how fixes flow to the existing Claude Fleet Core consumer. If custody moves for only this module, name that bounded transfer explicitly; if it does not, give Fleet Core the same synchronization rule as UniFi. |

This is material because the first post-pilot retry fix would otherwise create two writable sources despite the repository's central custody rule.

### D5 — P1 — The generated-bundle contract is incomplete

The build-time bundling decision is sound, but the plan does not identify the input declaration or define exactly what each digest covers.

| aspect | evidence |
|---|---|
| missing declaration | Implementation unit U3 says the bundler reads a declared module list from the consumer, but its file list names only the bundler, its test, and the repository validator at `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:257-275`. No unit names a declaration file or schema. |
| manifest limit | Agent Plugins 1.0 has a closed root manifest and forbids assigning semantics to unknown top-level fields at [`spec/1.0.0.md:141-147`](https://github.com/agentplugins/agent-plugins-spec/blob/main/spec/1.0.0.md#L141-L147), while requirement R20 correctly forbids inventing a dependency field at `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:70-76`. |
| digest ambiguity | The plan alternates among a module content digest, a stamp embedded in the generated file, and a digest of the generated file at `:261-273`. It does not define whether the stamp is excluded from hashing, how source staleness differs from bundle tampering, or where the Fleet Core version comes from. |
| required correction | Name a separate portable build-declaration path and closed schema, define the generation and check-only commands, identify the version source, and define both the source-payload and generated-output digest domains so stale source and hand-edited output fail for different, deterministic reasons. |

This is material because the declared model cannot be implemented inside the closed plugin manifest, and a digest embedded in the bytes it hashes is otherwise self-referential.

### D6 — P1 — The optional site-profile path is not executable end to end

The plan preserves optional operation and the no-inference rule, but it leaves the storage and integration decisions needed to make those guarantees real.

| aspect | evidence |
|---|---|
| unresolved storage and format | Requirements R10 through R15 require a remembered configured path and environment override at `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:50-62`. Implementation unit U8 names a YAML profile but no deployed runtime path at `:357-375`, while the dependency-bearing CI job lists `requests`, `urllib3`, and `pytest` but no YAML or JavaScript Object Notation (JSON) Schema runtime at `:468-476`. |
| missing user path | Implementation unit U4 says first setup offers exactly three choices, but its files contain a library, schema, test, and reference only at `:277-295`; no skill, command, adapter, or other entrypoint owns presenting or remembering that choice. |
| unsafe proposal ambiguity | Implementation unit U4 says the profile carries intended meaning and nothing else and forbids inferred intent at `:287-295`, while implementation unit U5 generates a proposed profile from actual controller discovery at `:297-315`. The plan does not say which fields may be prefilled or require a test that all trust, ownership, criticality, and policy fields remain unknown. |
| cross-repository gap | Implementation unit U7 requires the upstream Claude agent to consume the U4 profile contract, but its Claude-repository file list contains no profile loader or adapter at `:337-355`; the only loader named by U4 lives in this target repository. |
| required correction | Choose the profile serialization and validator dependency, the shared configured-path store, the exact machine-local deployment path, the setup entrypoint, and the cross-repository adapter. Define proposed-profile output as observed fields plus explicit unknown intent, or as an empty intent template, and test that it never infers operator meaning. |

This is material because the current text can produce a YAML file a dependency-free runtime cannot parse, an optional profile that no client can select, or a discovery proposal that violates the no-inference requirement.

### D7 — P1 — Release activation does not yet prove no capability gap

Pre-activation evidence is necessary, but it cannot by itself prove that the activated marketplace bytes and a fresh Claude session use the replacement context path.

| aspect | evidence |
|---|---|
| incomplete activation unit | Implementation unit U9 names only unspecified “release artifacts,” the UniFi changelog, and a public evidence file at `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:377-395`. It does not name the UniFi plugin manifest, the root marketplace manifest, a staged pre-activation loading command, or a post-activation installed-version readback. |
| authoritative release gate | The Claude repository requires generated marketplace parity and version equality across the plugin manifest, marketplace entry, and changelog at [`.github/workflows/ci.yml:132-152`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/995a475/.github/workflows/ci.yml#L132-L152) and [`scripts/check_release_surface_parity.py:1-6`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/995a475/scripts/check_release_surface_parity.py#L1-L6). |
| rollback gap | The plan says rollback after activation means “releasing the prior version” at `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:478-488`, but it does not define a reachable rollback version, marketplace refresh, client downgrade or replacement version, fresh-session confirmation, or the failure that triggers rollback. |
| required correction | Name every release surface and the exact staged pre-activation path, then require marketplace refresh, installed-version and digest readback, and a fresh Claude session that proves the profile-present, profile-absent, and unreadable-profile cases after activation. Define a tested rollback command and version strategy that restores prior behavior and repeats the fresh-session proof. |

This is material because source-tree evidence can pass while the active client remains cached, loads the wrong version, or loses its site context after the irreversible-feeling step.

### D8 — P1 — Ten rows do not prove ten complete smoke assessments

The plan correctly says every client must be assessed and that not every client must pass, but its acceptance check proves row count rather than stage coverage.

| aspect | evidence |
|---|---|
| promised coverage | Requirements R22 through R25 require installation or supported placement, discovery, loading, and the safest meaningful credential-free or read-only invocation for all ten clients at `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:78-86`. |
| weak gate | Implementation unit U11 requires one overall status, evidence, a reason, and no mutating invocation, but its tests and verification only assert ten rows and permitted overall statuses at `:417-435`. Its file list owns only the matrix document, not a validator or test, and a row can satisfy the prose checks after one early failure without recording what happened at every remaining stage. |
| required correction | Give every client four stage results—placement, discovery, load, and invocation—each marked executed, blocked, or not applicable with command and evidence, followed by exactly one overall status. Keep all ten rows mandatory, keep unsupported and failed as acceptable assessment outcomes, and retain the operator pause before any remediation. |

This is material because the current count gate can call a client “covered” without proving package loading or any meaningful invocation.

### D9 — P1 — Public evidence has no sanitization contract

The plan says site-identifying content is excluded, but the evidence-producing units do not define how that exclusion is enforced.

| aspect | evidence |
|---|---|
| sensitive inputs | Requirement R14 forbids committing raw discovered inventory and sensitive identifiers at `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:58-62`, and requirement R27 makes raw controller output default-deny for persistence at `:88-93`. |
| public output risk | Implementation unit U9 writes commands and results proving fact-by-fact equivalence into this public repository at `:377-395`; the ownership table says site-identifying content is excluded at `:457-466`, but no schema, field allowlist, redaction rule, or automated check makes that true. |
| repository rule | Public guidance forbids credentials and local environment material at `docs/public-safe-summary.md:5-14`, and the repository instructions require generated validation fixtures to use inert examples. |
| required correction | Define a public evidence schema that records field names, counts, pass/fail comparisons, source and result digests, and redacted commands without raw topology or controller responses. Keep the sensitive receipt private, link it only by non-sensitive digest or identifier, and test the public artifact against inert example values. |

This is material because the evidence step is specifically designed to compare private topology and would otherwise make publication safety depend on reviewer memory.

### D12 — P1 — The upstream documentation repair has no complete test owner

The plan promises regression assertions for the known documentation drift, but the implementation unit that needs them cannot create or update a test under its declared file boundary.

| aspect | evidence |
|---|---|
| required repair | Requirements R5 through R7 cover the Protect skill, plugin README, slash command, changelog, agent definition, both API references, and missing Network capabilities at `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:38-48`. |
| missing ownership | Implementation unit U6 lists only documentation and manifest files at `:317-335`; it names no test file even though its test scenarios require new parser-to-document and endpoint assertions. |
| incomplete stated assertions | The U6 scenarios check commands named in the two skills, paths named in the two references, and the plugin manifest description. They do not check the README, slash command, agent definition, or changelog that requirement R5 also requires to stop promising the four removed Protect capabilities. |
| required correction | Add the exact upstream test paths to implementation unit U6 and map every R5 through R7 surface to an assertion or an explicit review gate. If implementation unit U7 owns the shared test files instead, move the tests and U6 completion gate there deliberately rather than leaving U6's verification impossible within its file list. |

This is material because the pilot was created after false capability claims survived across multiple documents; leaving half those surfaces outside the regression gate permits the same failure to survive the repair.

### D10 — P2 — The deferred Fleet Core count is stale

The bounded slice is still correct, but the prose count cannot be used as an inventory assertion.

| aspect | evidence |
|---|---|
| stale plan text | Implementation unit U2 and the scope boundary say sixteen modules remain unported at `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:237-255` and `:490-500`. |
| source count | At source commit `995a475ba78757f2f62df2bbd6e0078d8523eaf4`, `plugins/fleet-core/scripts/fleet_commons/` contains fifteen Python modules total, so fourteen Python modules remain after `retry_backoff.py` is ported. The same directory also contains three JSON data files, and `plugins/fleet-core/scripts/fleet_commons_shim.py` is another unported Python module; no consistent “module” definition produces sixteen remaining modules. |
| required correction | Define whether the deferred inventory counts Python modules, data files, or all runtime support files, correct the prose count, and make `DEFERRED.md` completeness derive from the pinned source tree rather than from a handwritten number. |

This is P2 rather than P1 because implementation unit U2 already requires the generated inventory to name every upstream item; deriving it from source can prevent omission even though the plan's current count is wrong.

### D11 — P2 — The repository count is internally inconsistent

The unit map is understandable, but its stated count is wrong unless a fourth repository is missing from the plan.

| aspect | evidence |
|---|---|
| stale plan text | The plan says four repositories are touched at `docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md:457-466`, and the PR #2 body repeats that count. |
| actual map | The ownership table names only `infiquetra-agent-plugins`, `infiquetra-claude-plugins`, and `home-lab`; its fourth row repeats `infiquetra-agent-plugins` for two evidence artifacts. Implementation-unit ownership at `:213-215` also describes only those three repositories. |
| required correction | Change the count to three everywhere, or name the omitted fourth repository and assign its units, authority, dependencies, files, tests, and stop condition. |

This is P2 because the existing rows still identify where every currently defined unit belongs, but the mismatch undermines the cross-repository authority summary and the PR reviewer note.

## What the plan gets right

The core operator choices are present and should survive remediation.

| reviewed concern | result |
|---|---|
| settled operator decisions | The authoritative-source-first correction, void decision audit trail, relocation rather than deletion, optional profile, no-inference rule, bounded Fleet Core module, generated bundling, ten-client coverage, non-all-pass outcome, and operator pause are all present. |
| bounded Fleet Core slice | The source module is self-contained apart from Python standard-library imports, and its authoritative test file contains ten deterministic tests; the plan does not broaden the port to the rest of Fleet Core. |
| optional site profile | Requirements R10 through R15 make absence valid and require explicit unknowns rather than inferred intent. Finding D6 concerns the missing executable contract, not the optionality decision. |
| ten-client policy | The plan names Claude Code, OpenAI Codex, Cursor Agent, Qwen, Grok, OpenCode, Gemini CLI, Muse, Agy, and Hermes, and explicitly allows unsupported or failed outcomes. Finding D8 preserves that policy while requiring stage-complete evidence. |
| operator pause | Requirement R25, KTD5, implementation unit U12, the non-goals, deferred work, and the stop conditions all prohibit automatic client remediation. |
| authority stops | The plan states that the current session cannot change `infiquetra-claude-plugins` or `home-lab`, and it stops before both repositories and before release activation. Finding D2 requires the outer controller to carry those stops across actual runs. |
| read-only live behavior | The plan prohibits `--confirm`, mutating operations, and raw controller-output persistence. No live controller operation was run during this review. |

## Checks and evidence limits

The verdict is based on the exact PR head, current repository files, source commit `995a475ba78757f2f62df2bbd6e0078d8523eaf4` in `infiquetra-claude-plugins`, the clean current `home-lab` checkout, the published Agent Plugins 1.0.0 and Agent Skills specifications, and the current installed Saga and Orchestrate contracts.

Repository validation is relevant only to document syntax and links; it cannot resolve the P1 findings above. No implementation tests, client smoke tests, release, installation, credential access, UniFi controller call, Saga-state mutation, or external-system mutation was performed.

| check | result |
|---|---|
| `PYTHONDONTWRITEBYTECODE=1 python3 scripts/check_repo.py` | passed |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v` | passed; 4 tests |
| `git diff --check` | passed |

The Claude-repository test collection was not used as approval evidence because its configured coverage plugin attempted to write `.coverage` in the read-only checkout and the sandbox refused the write. Source inspection independently confirmed the ten `retry_backoff` test functions and the release-surface gates needed for this plan review.
