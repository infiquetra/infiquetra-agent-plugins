# Custody move and retirement of infiquetra-claude-plugins

**Date:** 2026-09-22. **Status:** approved run plan (operator goal set in
session; this document is the record). **Owner:** repository maintainer.

## Goal, in one paragraph

Every coding-agent harness on the operator's Mac Studio — Claude Code, OpenAI
Codex, Grok, Muse, OpenCode, Qwen, Agy, Hermes, Gemini CLI, and Cursor Agent —
installs Infiquetra plugins from this repository, `infiquetra-agent-plugins`,
instead of from `infiquetra-claude-plugins`. When that is verified live, the
old repository is retired (archived read-only on GitHub). Claude Code reads
`AGENTS.md`, so the repository-level guidance also no longer needs a
Claude-only home.

## What this reverses

The 2026-08-21 pilot decision ("Choose the first portability pilot and custody
gate", now in `ARCHIVE.md`) resolved the custody gate by *not moving*: the
Claude repository stayed authoritative and this catalog derived from it by
digest-verified synchronization. That question was left "deliberately
unanswered until the pilot produces evidence". Three ports and one authored
package later, the evidence exists, and the operator has decided: custody moves
here. The decision entry is dated 2026-09-22 in `DECISIONS.md`.

## Starting state (verified 2026-09-22 against `origin/main` of both repos)

Upstream `infiquetra-claude-plugins` is at `acc99fe7` and registers 13 plugins
(`team-execution` was archived upstream and is out of scope).

| Package | Upstream | Here | Disposition |
|---|---|---|---|
| agent-launcher | 1.7.0 | ported at 1.0.0 (stale) | core only (no Claude surfaces) |
| agy | 0.6.1 | — | core + Claude adapter; author a portable skill over the delegation script |
| codex | 0.1.4 | — | core + Claude adapter; author a portable skill over the delegation script |
| deploy | 0.2.2 | — | core + Claude adapter; author a portable skill over the deploy scripts |
| fleet-core | 0.32.0 | 4-module slice at 0.25.2 (stale) | core only, full module set |
| hermes-profile-evolution | 0.1.4 | — | Claude adapter only (hook + command); **retirement candidate, operator to confirm** |
| home-lab-ops | 1.2.1 | — | core (6 skills) + Claude adapter (1 agent) |
| house-style | 0.1.0 | — | Claude adapter only (an output style is Claude-specific by nature) |
| mission-control | 2.21.0 | ported at 2.15.2 (stale) | core + Claude adapter (adapter already split) |
| orchestrate | 6.0.0 | — | core (orchestrate.py + skill) + Claude adapter (command) |
| redis-channel | 0.5.2 | — | core (MCP server, scripts, a portable skill) + Claude adapter (8 commands, agent) |
| saga | 1.2.0 | — | core (12 skills, scripts) + Claude adapter (14 commands, 5 hook events) |
| unifi | 2.0.6 | ported at 2.0.6 (current) | core + Claude adapter (adapter already split) |
| voice | — | authored here 0.4.0 | unchanged; it is the model the others follow |

Dispositions were scored by TypeSafe Jev over the policy in this section and
then decided by the lead. Overrides with reason: `orchestrate` scored "retire"
at low confidence, but it is in daily use on this machine (this repository's
own work ran through it), so it is ported. `agy`, `codex`, `deploy`, and
`redis-channel` scored "adapter only" at low confidence; each carries scripts
other harnesses can run once a portable skill describes them, and the goal is
that other harnesses can use them, so they are split core + adapter with the
skill authored in the port. `hermes-profile-evolution` scored "retire" at 0.78;
it is carried as adapter-only so nothing is lost, and retirement is a one-line
operator call.

## Rules that change, and rules that do not

**Changes.**

1. **Authored-here becomes the norm.** A package with no `PROVENANCE.json` is
   authored here (this is already how `check_repo.py` reads it). After import,
   every package drops its `PROVENANCE.json`; the import commit and upstream
   SHA are recorded once in the package `CHANGELOG.md` and in the decision
   entry. There is no upstream to pin after the old repository is archived.
2. **Port descriptors gain an authored mode** (schema version 4): `source` and
   `custody` become optional; the `assessment` block stays mandatory because
   `assess_clients.py` and `check_compatibility_matrix.py` read it and its
   safety fields must still be stated, never defaulted.
3. **Every package is Claude-installable from this repository.** Each package
   root carries `.claude-plugin/plugin.json` pointing into
   `com.infiquetra.claude/`, and the root `marketplace.json` lists every
   package. The 2026-08-25 decision "Claude installs the package root" already
   defines the layout; the agent-launcher test that asserted the marketplace
   lists voice only (`QUEUED.md` P1, "withheld pending an operator decision")
   is retired because this is that decision.
4. **Compatibility evidence binds to a released version, not to every tree.**
   For a derived package, every byte came from one pin, so binding a matrix to
   the tree fingerprint was right. For an authored package the tree moves on
   every commit and a per-commit ten-client run is not a standard anyone will
   keep. The rule becomes: a matrix records the package `version` and the
   fingerprint it assessed; the check fails when the current `version` has no
   matrix, and reports (without failing) when the tree moved under an
   unchanged version. A version bump therefore requires a fresh run.

**Unchanged.**

- Vendor-neutral core at the package root; Claude behaviour only under
  `com.infiquetra.claude/`; the two Claude manifests carry paths, never
  behaviour (`tests/test_claude_plugin_packaging.py`, generalized to every
  package that has a Claude manifest).
- Fleet Core is bundled at build time (`bundle_fleet_module.py`), never
  imported by discovery; `fleet_commons_shim.py` does not cross the boundary.
- A portable package must be runnable, not merely present
  (`tests/test_client_entrypoints.py` pattern).
- `check_repo.py` stays standard-library-only and network-free.
- No credentials in fixtures; credential prefixes stripped in assessment.

## Units

| Unit | What | Executor | Depends on |
|---|---|---|---|
| U0 | This plan, the decision entry, a tracking issue | lead | — |
| U1 | Tooling for authored mode: descriptor v4, `scripts/import_vendor_package.py`, generalized Claude packaging test, full marketplace, version-bound evidence check | Claude Opus subagent, own worktree | U0 |
| U2 | fleet-core full import at `acc99fe7`; regenerate consumer bundles | Grok 4.7 session, worktree | U1 |
| U3.x | One import per package (12), each in its own worktree and branch `mg/<pkg>` | Grok 4.7 sessions, ≤10 in flight | U1; fleet consumers also on U2 |
| U4 | Triage of the 179 repo-wide upstream tests and `tools/`: carry / rewrite / drop table | Claude Sonnet subagent | — |
| U5 | `scripts/install_client.py`: place the catalog per harness, `--check`, `--dry-run`, and removal of the old placements | Grok 4.7 session | U1, harness survey |
| U6 | Ten-client assessment per package on this machine, evidence committed | Grok 4.7 session | U3.x, U5 |
| U7 | Cutover: repoint every harness, verify live, remove the old marketplace, archive upstream (operator confirms the archive) | lead | U5, U6 |
| U8 | Adversarial review of the merged branches before cutover | Claude Opus subagent | U3.x |

Fan-out is bounded at ten concurrent sessions. Each Grok unit runs in a git
worktree under `/Users/jefcox/workspace/infiquetra/mg-<name>`, on branch
`mg/<name>`, and ends with a pull request that passes CI; the lead merges.

## The per-package recipe (U3)

1. `python3 scripts/import_vendor_package.py --package <pkg> --source <upstream checkout> --commit acc99fe7`
   lays the package out: portable core at the root, Claude surfaces
   (`commands/`, `agents/`, `hooks/`, `.mcp.json`, output styles) moved under
   `com.infiquetra.claude/`, the upstream `.claude-plugin/plugin.json`
   relocated into the adapter, a new root `.claude-plugin/plugin.json`
   pointing at the adapter, a portable `plugin.json`, `SKILL.md` frontmatter
   normalized, `fleet_commons_shim` loads rewritten to the bundled copy, and a
   `fleet-bundle.json` declaring the modules it reaches.
2. Fix what the transform could not: relative paths in skills and commands
   that assumed the upstream layout; tests that assumed the upstream repo.
3. Where the package had commands but no skill, author one `SKILL.md` per
   capability so skill-scoped harnesses can reach the scripts.
4. Port the package's own tests under `plugins/<pkg>/tests/`; drop upstream
   tests whose premise is the upstream repository, and say so in `CHANGELOG.md`.
5. Run `python3 scripts/bundle_fleet_module.py`, `python3 scripts/check_repo.py`,
   `python3 -m unittest discover -s tests`, `python -m pytest plugins/<pkg>/tests -q`,
   `git diff --check`.
6. `CHANGELOG.md`: one entry, "imported from infiquetra-claude-plugins@acc99fe7
   (upstream version X); authored here from this commit". Keep the upstream
   version number and bump patch.
7. Open the pull request with the checklist above filled in.

## Pre-mortem

The most likely failure is ceremony: treating each of twelve imports as a
fourteen-round port with fingerprint-bound evidence, and never cutting over.
The mitigations are rules 1 and 4 above and the fixed recipe. The second most
likely failure is a harness that discovers packages only from a git URL or a
marketplace manifest this repository does not ship (Codex, Cursor); U5 has to
produce a working placement for each harness on this machine or record it as
unsupported with the reason, and cutover does not wait on an unsupported
harness that never consumed the old repository either.

## Stop conditions

- A Grok unit that cannot get the package's own tests green without editing
  portable core semantics stops and reports; the lead decides.
- Any assessment stage that needs a credential stays blocked, never faked.
- The upstream archive happens only after the operator confirms, and only
  after every harness on this machine has been read back as installed from
  this repository.
