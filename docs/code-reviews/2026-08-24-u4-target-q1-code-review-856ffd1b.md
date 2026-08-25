# Saga Code Review — U4 target-owned surface (`u4-target-q1`)

This review covers the frozen Lane B commit on `orch/mcport-9-resume1-u4-target-q1` because the portable manifest and package README are the consumer-facing identity of the mission-control package, and a byte-copied upstream README is the failure class the UniFi pilot already shipped.

## Outcome

- Typed Saga review result contract (`review_result.v1`): `accepted`
- Next action: `continue`
- Reviewed revision: `856ffd1bb5e7d52902636967a24fbd9dca43daaf` (`856ffd1`, `feat(mission-control): add the portable manifest, package README, and enforcement test (run unit U4)`)
- Named base: `d7d49d8def9e4eb064e0cc9ab501ff0ea7556340`
- Target: `plugins/mission-control/plugin.json`, `plugins/mission-control/README.md`, `tests/test_mission_control_readme.py`, `docs/engineering-journal/DECISIONS.md` (one commit, `+651`)
- Review backend: `inline`
- Active findings: none
- Cycle: 1 of 3; no repairs requested

> **Verdict: revision `856ffd1` is accepted under the roster contract.** Every selected lens has a derived overall of at least 9.0 and every applicable dimension is at least 7.0. The owned surface is exactly Lane B. Assertions that need Lane A or Lane C artifacts skip with a named reason. Independent gates this controller ran at the frozen revision all passed.

## Scope and built-versus-planned audit

**Scope Check: CLEAN**

- Intent (issue #14 / plan U4): author the portable `plugin.json` and a target-owned README that documents the portable package, plus `tests/test_mission_control_readme.py` following `tests/test_unifi_readme.py`.
- Delivered: those three files plus the authorized same-commit journal entry. No `com.infiquetra.claude/`, no `PROVENANCE.json`, no `fleet-bundle.json`, no synced scripts.

Child #14's `python3 scripts/check_repo.py` green line is **CHANGED** against the landing model: creating the package directory turns the prior "not a directory" completeness error into five missing-entrypoint errors. That is still the named package-completeness class the contract allows until Lane A lands the tree. No markdown-link or manifest errors were added.

### Plan-completion (U4)

| Item | State | Evidence |
| --- | --- | --- |
| Portable manifest at package root, version 2.12.2 | DONE | `plugins/mission-control/plugin.json`; `$schema` Agent Plugins 1.0; `check_plugin_manifests` empty |
| README identifies the portable package; not a Claude Code plugin; no stale cache path | DONE | lede starts "Portable Agent Plugins 1.0 package"; `.claude/plugins/cache` and `2.1.0` absent |
| All seven skills including `flow`; mutating/read-only split; `gh` delegation; `INFIQUETRA_SDLC_PATH`; PyYAML; network-first `sdlc-schema` | DONE | README tables; pin-verified schema order is GitHub `main` then vendored then local |
| Enforcement test follows UniFi pattern with `GH_`/`GITHUB_` strip; skip-when-absent for Lane A/C | DONE | 8 tests, 2 skipped with reasons naming the missing sentinel paths |
| No documented mutating invocation | DONE | fenced commands are `--help` and repository checks; mutating verbs are a table, not fences |
| Relative links resolve on this branch | DONE | 11 relative links, all exist; Lane A/C paths are literals |
| Full `check_repo.py` green | CHANGED / deferred | five descriptor entrypoint-completeness errors only |

COMPLETION: 6/7 DONE, 1 CHANGED.

## Lens scores

The canonical lens roster accepts a lens only when its mean applicable-dimension score (`derived_overall`) is at least 9.0 and every applicable dimension is at least 7.0.

| Lens | Derived overall | Accepted | Failing dimensions with scores |
|---|---:|---|---|
| `architecture-maintainability` | 10.00 | `true` | none |
| `correctness` | 10.00 | `true` | none |
| `security` | 10.00 | `true` | none |
| `testing` | 10.00 | `true` | none |
| `documentation-clarity` | 9.83 | `true` | none |
| `adversarial` | 10.00 | `true` | none |
| `api-contract` | 10.00 | `true` | none |

## What was verified

### Filesystem custody and owned surface

`git ls-tree` of `plugins/mission-control/` at this revision is only `plugin.json` and `README.md`. `com.infiquetra.claude/`, `PROVENANCE.json`, and `fleet-bundle.json` are absent. The journal records that relative links bind only what Lane B lands; later-lane paths are unlinked literals so `check_markdown_links` stays green on this branch.

### `gh` credential handling and GitHub mutation surface

The README states scripts read no token variables and that assessment strips `GH_` and `GITHUB_`. The enforcement test's runnability path builds an environment that drops every `GH_`/`GITHUB_` variable before `subprocess.run`. That path is skipped on this branch because `scripts/sdlc_manager.py` is absent; the skip names Lane A. Fenced commands are usage probes and repository checks; `test_no_fenced_command_is_a_mutating_invocation` always runs. Mutating CLI verbs are pinned to `ports/mission-control.json`'s `assessment.mutating_operations` (underscore-prefixed `_open_mapping_pr` excluded as a non-verb) and each verb appears in the README table. `_open_mapping_pr` is documented as the internal mapping-PR path.

Local writes (`issue prepare`, `config init-defaults`, `rollout update`) are disclosed as GitHub-read-only with local side effects, matching the U1 audit.

### Manifest and README claims

`plugin.json` matches UniFi's required fields plus the keywords the child asked for. Version is `2.12.2`. Description names the Claude adapter directory as adapter, not identity.

Network-first `sdlc-schema` and local-first `project-mappings` match `sdlc_manager.py` at pin `84eaf042` (GitHub `main` then vendored then local checkout; mappings: `INFIQUETRA_SDLC_PATH`, vendored, then remote). Fleet Core "three files" (`intent_envelope`, `tier_palette`, `models.json`) matches KTD8 on this lineage, not the original two-module U5 sentence.

### Tests at the frozen revision

`python3 -m unittest tests.test_mission_control_readme -v`: 8 tests, 2 skipped, 0 failed.

- Skip 1: runnability — `plugins/mission-control/scripts/sdlc_manager.py` absent (Lane A).
- Skip 2: PROVENANCE target-owned custody — `PROVENANCE.json` absent (Lane A).

`check_plugin_manifests` is empty. `git diff --check` is clean. `check_repo.py` reports only the five missing entrypoints.

## Coverage

- Suppressed findings: 0.
- Residual risks, not findings:
  - Child #14's full-gate-green line waits on Lane A. Error shape changed from one "not a directory" to five missing entrypoints because this unit created the package directory; still the allowed completeness class.
  - Runnability and `GH_` stripping are unexercised until both `sdlc_manager.py` and `scripts/_bundled/tier_palette.py` exist. That is the skip contract, not a silent pass.
  - Documentation-clarity / runnable-examples is 9 because the child's "every documented `python3` command runs with exit 0" is not executed on this branch; usage-probe fences are the right surface, and live subcommands would force a GitHub call.
- Independent gates actually run at `856ffd1`: README tests 8/8 (2 skip with reason); plugin-manifest check empty; relative links resolve; `git diff --check` exit 0. `evaluate_review_readiness` can_proceed is true.

## Findings

None.

## Routing

`accepted` — continue to the caller's next independent gate. No fix requests.
