# Home lab operations

Portable Agent Plugins package for operating a Proxmox VE and Ceph cluster
with Ansible: preflight checks, inventory change lists, monitoring guards,
vault workflows, and a generator that stands up an agent-team repository.
The procedures live in the skills. Claude-only behavior is the
`homelab-sre` agent under the client extension directory. This package does
not ship a Fleet Core bundle and does not read credentials from the
environment.

The package is authored in this repository from
`infiquetra-claude-plugins` commit `acc99fe7` (upstream version 1.2.1). There
is no provenance manifest. The import and the changes made while authoring
it are in [CHANGELOG.md](CHANGELOG.md).

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Agent Plugins manifest. Vendor-neutral. |
| [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) | Claude Code packaging manifest. Paths only: the agent directory under `com.infiquetra.claude/` and the portable `skills/` directory. |
| [`skills/ansible-preflight/`](skills/ansible-preflight/SKILL.md) | Checks to run before an Ansible change is applied. |
| [`skills/inventory-sync/`](skills/inventory-sync/SKILL.md) | File checklist for a hardware or address change. |
| [`skills/monitoring-guard/`](skills/monitoring-guard/SKILL.md) | Exporter, dashboard, and scrape-target checks. |
| [`skills/proxmox-operations/`](skills/proxmox-operations/SKILL.md) | Proxmox VE 9 and Ceph command patterns. |
| [`skills/vault-helper/`](skills/vault-helper/SKILL.md) | Ansible Vault edit, add, and rotation steps. |
| [`skills/team-scaffold/`](skills/team-scaffold/SKILL.md) | Generator and validators. The runnable command is here. |
| [`com.infiquetra.claude/`](com.infiquetra.claude/plugin.json) | Claude adapter: manifest and the `homelab-sre` agent. |
| [`tests/`](tests/) | Pytest suite for the generator, the validators, and the launcher. |

The five knowledge skills have no script. `team-scaffold` does. Its
dependencies and the two checkout variables are in
[`skills/team-scaffold/README.md`](skills/team-scaffold/README.md).

## How a harness reaches it

Claude Code installs this package from the repository marketplace. The
install root is this directory, so the skills and the adapter travel
together. The agent is `homelab-sre`.

OpenCode, Gemini CLI, Muse, and Hermes are skill-scoped. Point each of them
at a directory under [`skills/`](skills/). Each directory has a `SKILL.md`
whose `name` is the directory name.

The generator does not need a harness:

```bash
python3 plugins/home-lab-ops/skills/team-scaffold/scripts/team-scaffold --help
```

PyYAML has to be importable. `--help` does not read a checkout and does not
read a credential.

## Checkouts

`HOME_LAB_ROOT` defaults to `~/home-lab`. `register-host` reads
`$HOME_LAB_ROOT/ansible/inventory/hosts.yml`.

`INFIQUETRA_CONTEXT_LIBRARY` defaults to `~/infiquetra-context-library`.
`stamp` copies archetype templates from that checkout.

Set either variable when the checkout is not in the home directory under
that name.

## Tests

From the catalog repository root:

```bash
python3 -m pytest plugins/home-lab-ops/tests -q
```
