# Changelog

## [1.2.2] - 2026-09-22

1.2.2 — imported from infiquetra-claude-plugins@acc99fe7 (upstream 1.2.1); authored here from this commit; no provenance manifest from now on.

### Changed

- The portable core stays at the package root. The Claude agent and the upstream Claude manifest moved under `com.infiquetra.claude/`. A root `.claude-plugin/plugin.json` points at that adapter and carries no behavior. There is no Fleet Core dependency and no `fleet_commons_shim`.
- `HOME_LAB_ROOT` (default `~/home-lab`) and `INFIQUETRA_CONTEXT_LIBRARY` (default `~/infiquetra-context-library`) replace checkout paths that named one machine's home directory. `register-host`, `stamp`, and `materialize_specs.py` read those variables. The defaults are conventional directory names.
- The README describes the portable package and the Claude adapter. It no longer records a cluster address map or a checkout path.
- The team-scaffold skill does not vendor a virtual environment. `skills/team-scaffold/README.md` names PyYAML and the development tools. The upstream pin did not contain a `.venv`; the import also excludes that directory name.
- The example shared-infra vault names the SSH key fields with `change-me` and no private-key block, so the publication check does not see key armor. The twelve golden vault fixtures were regenerated from that template.
- A generated play comment that looked like an assignment to `secrets` was reworded. The twelve golden playbooks were regenerated from the same template.
- Example secret values in the vault skill are `change-me`. `discord_token_var` lines keep the Ansible variable name the validator requires, and say on the same line that the value is a variable name.
- `repo_stamp` writes that same note when it stamps a `discord_token_var` line.
- Tests that lived under `skills/team-scaffold/scripts/tests/` now live under `plugins/home-lab-ops/tests/`. The inventory unit fixture uses documentation addresses. Context-library stamp tests skip when `INFIQUETRA_CONTEXT_LIBRARY` is unset.

### Not carried

These upstream tests mention the package and were not copied. Their premise is the upstream repository, not this package:

- `tests/test_agent_preamble_identity.py` — one fleet-wide list of agent files. Repo-wide.
- `tests/test_agent_tiering.py` — one fleet-wide model pin list. Repo-wide.
- `tests/test_release_triad.py` — repository changelog and marketplace lockstep. This package appears only as an example of a heading format.

No test whose premise is this package's generator, validator, or launcher was dropped.

## [1.2.1] - 2026-08-08

### Added - house-style presentation contract on the SRE agent (#704)

- `homelab-sre` agent definition gains a "Presentation contract (Infiquetra house style)" section, copied verbatim from `plugins/house-style/references/subagent-presentation-preamble.md`.

## [1.2.0] - 2026-06-21

### Changed
- `homelab-sre` agent: pin `model: opus` in frontmatter (R1/R2a tiering; judgment-heavy SRE
  diagnosis warrants the richest model).

## [1.1.0] - 2026-06-01

### Added
- `team-scaffold` skill — stands up a new infiquetra agent-team repo end-to-end
  (context-library-compliant skeleton + Discord/GitHub identity gates + split-vault
  wiring + Ansible deploy harness). Promotes the polyrepo-migration generators
  (`gen_harness.py`, `vault_split.py`) into a tested `team_scaffold` Python package
  with a golden test that reproduces all 12 live `infiquetra/team-*` repos
  byte-for-byte, plus a `team_profiles.yml` validator calibrated against every
  live team config. Closes acceptance criterion #7 of the home-lab polyrepo migration.

## [1.0.0] - 2026-03-17

### Added
- `ansible-preflight` skill with `common-mistakes.md` reference — catalog of fix patterns extracted from home-lab commit history
- `proxmox-operations` skill with `proxmox-cli-quirks.md`, `ceph-operations.md`, `vm-lifecycle.md` references — PVE 9.x and Ceph Squid 19.x operational knowledge
- `inventory-sync` skill with `inventory-schema.md` reference — hardware change checklists and variable dependency map
- `monitoring-guard` skill with `metric-registry.md` reference — exporter metric names and dashboard validation
- `vault-helper` skill with `vault-patterns.md` reference — Ansible Vault workflows and secret scaffolding
- `homelab-sre` agent — cross-cutting SRE investigation agent combining all skills
