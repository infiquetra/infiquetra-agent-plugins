# UniFi portable package

Portable Agent Plugins 1.0 package for UniFi Network and UniFi Protect. It
ships two Agent Skills with their bundled Python clients, an operator site
profile contract, and credential-safe discovery and drift tools. Claude-only
files live under the client extension directory
[`com.infiquetra.claude/`](com.infiquetra.claude/plugin.json); they are an
adapter, not the identity of this package.

This tree is a derived artifact of `infiquetra-claude-plugins` at the commit
recorded in [`PROVENANCE.json`](PROVENANCE.json). Custody has not moved.
Existing vendor repositories remain the runtime sources of truth.

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Agent Plugins 1.0 manifest |
| [`PROVENANCE.json`](PROVENANCE.json) | Source repository, pinned commit, and per-path custody |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history |
| [`fleet-bundle.json`](fleet-bundle.json) | Build declaration: which Fleet Core modules this package consumes |
| [`skills/unifi-network/`](skills/unifi-network/SKILL.md) | Network skill, API reference, and client |
| [`skills/unifi-protect/`](skills/unifi-protect/SKILL.md) | Protect skill, API reference, and client |
| [`scripts/`](scripts/site_profile.py) | Site-profile loader, first setup, discovery, and drift |
| [`references/site-profile.md`](references/site-profile.md) | Operator site-profile contract |
| [`schemas/site-profile.schema.json`](schemas/site-profile.schema.json) | Schema the loader validates against |
| [`com.infiquetra.claude/`](com.infiquetra.claude/plugin.json) | Claude adapter: manifest, slash command, agent definition |

The network client covers twelve resource groups: devices, clients, networks,
firewall, traffic routes, port forwards, WLANs, VPN, DNS, DHCP, stats, and
backup. The Protect client covers six: cameras, liveviews, lights, sensors,
chimes, and viewers. The command catalog lives in the skills; this README
does not duplicate it.

## Client extension directory

Agent Plugins 1.0 section 8.2 puts client-specific files in an explicit
extension directory rather than at the package root. This package's Claude
adapter is [`com.infiquetra.claude/`](com.infiquetra.claude/plugin.json):

| Path | What it is |
|---|---|
| [`plugin.json`](com.infiquetra.claude/plugin.json) | Claude Code manifest, relocated from upstream `.claude-plugin/` |
| [`commands/unifi.md`](com.infiquetra.claude/commands/unifi.md) | Slash command |
| [`agents/unifi-network-ops.md`](com.infiquetra.claude/agents/unifi-network-ops.md) | Agent definition |
| [`site_profile_loader.py`](com.infiquetra.claude/skills/unifi-network/scripts/site_profile_loader.py) | Claude-side profile loader |

The portable manifest, skills, schemas, and scripts beside that directory
carry no Claude loading convention.

## Fleet Core bundle

The clients need one shared primitive, `retry_backoff`. Agent Plugins 1.0 has
no dependency field, so this package does not install Fleet Core at runtime.
[`fleet-bundle.json`](fleet-bundle.json) declares the module and its
destinations, and
[`scripts/bundle_fleet_module.py`](../../scripts/bundle_fleet_module.py)
copies it into each skill as a generated, digest-stamped file:

- [`skills/unifi-network/scripts/_bundled/retry_backoff.py`](skills/unifi-network/scripts/_bundled/retry_backoff.py)
- [`skills/unifi-protect/scripts/_bundled/retry_backoff.py`](skills/unifi-protect/scripts/_bundled/retry_backoff.py)

Each client inserts that `_bundled/` directory on `sys.path` and imports
`retry_backoff` directly. The dropped `fleet_commons_shim` used Claude-specific
runtime discovery; this package does not ship it.

Verify the stamps without writing:

```bash
python3 scripts/bundle_fleet_module.py --check
```

The Fleet Core source is the sibling package
[`plugins/fleet-core/`](../fleet-core/README.md). Only `retry_backoff` is
ported; everything else is named in [`DEFERRED.md`](../fleet-core/DEFERRED.md).

## Operator site profile

The site profile is how an operator states intent a controller cannot report:
trust role, criticality, ownership, intended policies, and operational
constraints. It is optional. With no profile anywhere, the package loads in
discovery-only mode and infers none of those fields.

Resolution order, highest first, from
[`references/site-profile.md`](references/site-profile.md):

1. The `UNIFI_SITE_PROFILE` environment variable.
2. The path remembered in
   `${XDG_CONFIG_HOME:-~/.config}/infiquetra/unifi/config.json`.
3. No profile at all.

A missing file named by the environment variable does not fall back. A
configured path that has gone missing is reported as missing, not as
discovery-only. The documented default runtime path
`${XDG_CONFIG_HOME:-~/.config}/infiquetra/unifi/site-profile.json` is a
default *path*, not a default *profile*, and is not itself a resolution rung.

The profile never carries a credential. Validation is against
[`schemas/site-profile.schema.json`](schemas/site-profile.schema.json).

First-setup and inspection commands, from the repository root. None of them
opens a controller session:

```bash
python3 plugins/unifi/scripts/site_profile_setup.py --list
python3 plugins/unifi/scripts/site_profile.py --help
python3 plugins/unifi/scripts/discover.py --help
python3 plugins/unifi/scripts/drift.py --help
```

`--list` prints the three setup paths: existing profile, discovery proposal,
and discovery-only. Discovery is read-only and does not accept `--confirm`.
Drift compares an inventory to a profile; with no profile it reports
discovery-only and no findings.

## Running the clients

`UNIFI_API_KEY` and `UNIFI_HOST` are required; there is no default host.
`UNIFI_SITE` defaults to `default` for Network API calls. The clients live at:

- [`unifi_network_client.py`](skills/unifi-network/scripts/unifi_network_client.py)
- [`unifi_protect_client.py`](skills/unifi-protect/scripts/unifi_protect_client.py)

They import `requests` and `urllib3`. Write operations preview unless
`--confirm` is passed; do not pass `--confirm` unless you intend to mutate the
controller. The command surface is in the skills above.

This repository verifies both entrypoints without credentials or a network
call. That check is [`tests/test_client_entrypoints.py`](../../tests/test_client_entrypoints.py):

```bash
python3 -m unittest tests.test_client_entrypoints -v
```

## Validation in this repository

These commands run from the repository root. They install nothing and make no
network call:

```bash
python3 scripts/bundle_fleet_module.py --check
python3 scripts/check_repo.py
python3 plugins/unifi/scripts/site_profile.py --help
python3 plugins/unifi/scripts/site_profile_setup.py --list
python3 plugins/unifi/scripts/discover.py --help
python3 plugins/unifi/scripts/drift.py --help
python3 -m unittest tests.test_client_entrypoints tests.test_site_profile tests.test_site_profile_setup tests.test_unifi_readme -v
```

`python3 -m unittest discover -s tests -v` runs the full suite, including the
test that this README's relative links resolve and that every `python3`
command in a `bash` fence here actually runs.

## Live environment

Required for a live controller session; unused by the validation commands
above.

- `UNIFI_API_KEY` — UniFi OS API key (required)
- `UNIFI_HOST` — controller address (required; no default)
- `UNIFI_SITE` — Network API site slug (optional; default `default`)

Generate an API key in UniFi OS → Settings → API Keys. Addresses in this
document are RFC 5737 documentation addresses.

## Further reading

- [Site-profile contract](references/site-profile.md)
- [Portable Fleet Core](../fleet-core/README.md)
- [Repository commands](../../AGENTS.md)
- [Pilot plan](../../docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)
