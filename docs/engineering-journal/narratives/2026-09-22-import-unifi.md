# 2026-09-22 — import UniFi as authored source

UniFi was a derived port at 2.0.6. This branch imports it from
infiquetra-claude-plugins at `acc99fe7` and keeps it here. The package version
is 2.0.7.

## What the import did

`scripts/import_vendor_package.py --force` replaces `plugins/unifi/` wholesale.
The dry run classified 9 portable-core files, 3 Claude-adapter files, 2 dropped
shims, and 3 generated files (the root Claude manifest, the portable manifest,
and `fleet-bundle.json` declaring `retry_backoff`). No shim import was left
unresolved. Both clients were rewritten by `resolve-bundled-fleet-module`.

The replace deletes files that exist only in this repository. These were
copied aside and restored: `README.md`, `references/site-profile.md`,
`schemas/site-profile.schema.json`, `scripts/discover.py`, `scripts/drift.py`,
`scripts/site_profile.py`, and `scripts/site_profile_setup.py`. The upstream
README was not kept. It is the file the portable README was written to replace.

## Decisions

**The Claude site-profile loader stays in the adapter.** The import copies
`site_profile_loader.py` into the portable skill, because the script only
moves `commands/`, `agents/`, `hooks/`, and `.mcp.json`. The module's own
text says it is how the Claude adapter reads the profile, and the portable
core already has `scripts/site_profile.py` for the same contract. The file
lives at `com.infiquetra.claude/skills/unifi-network/scripts/site_profile_loader.py`.
The agent now calls that path. The old command used `plugins/unifi/skills/...`,
which is the upstream repository layout.

**The adapter manifest names this repository.** `relocate-claude-manifest`
keeps the upstream bytes, so the adapter `plugin.json` still said
`infiquetra-claude-plugins`. Custody is here, so `repository` is
`https://github.com/infiquetra/infiquetra-agent-plugins`. The version on the
portable manifest, the root `.claude-plugin/plugin.json`, and the adapter
manifest is 2.0.7.

**The DNS help example uses a documentation address.** The imported client
showed `192.168.1.10` in `--help`. The rest of the package uses RFC 5737
addresses. The help text now shows `192.0.2.10`. No test asserted the old
string.

**Two loader tests were not carried.** Upstream
`tests/test_unifi_site_profile_loader.py` embeds one site's topology
(the 10.220 prefix, host names, and a device model) and two tests whose
job is to prove that record was moved out of the agent and not lost. Publishing
that record in this repository would put the topology back. The contract tests
remain, against a profile whose addresses are RFC 5737 and whose site
identifier is `example-site`. The guard that the package tree contains no
lab-prefix literal remains, and it excludes `tests/` because the search string
lives in the test. The dropped tests are named in `plugins/unifi/CHANGELOG.md`.

**The portable README has no invocation floor.** Upstream's doc-match test
required the README to contain at least sixty client invocations. This README
is target-owned and says the command catalog lives in the skills. The floor
now applies to the two skills and the agent.

**Evidence for 2.0.6 is superseded, and 2.0.7 has no matrix.** A current
matrix whose recorded version is not the package version fails
`scripts/check_compatibility_matrix.py`. A superseded matrix must name a
successor that is current. There is no ten-client run for 2.0.7, and inventing
the rows would be a run that did not happen. `docs/evidence/2026-09-22-unifi-authored-cut.md`
is the successor. It is not a matrix. Every `2026-08-22-unifi-compatibility-matrix*.md`
file is superseded and points at it. The post-activation readback is marked
historical in prose and still contains the 2.0.6 record.

**`ports/unifi.json` keeps the assessment block and a one-line provenance
note.** `source` and `custody` are absent. The note names `_bundled/`, which
is the directory the clients import and the name `tests/test_port_config.py`
checks for in the shipped UniFi descriptor's notes.

## Follow-up: the shared files this change breaks

The three markdown links to `plugins/unifi/PROVENANCE.json`, in the repository
README, `LEARNINGS.md`, and `QUEUED.md`, now keep that filename as text and
point at `plugins/unifi/CHANGELOG.md`, with the same parenthetical the
Fleet Core import used.

`tests/test_sync_vendor_source.py` loads a synthetic derived descriptor from
`tests/fixtures/unifi.json` (inert repository `https://example.com/unifi-upstream`,
the historical custody paths). The shipped descriptor is asserted authored, and
`load_config("unifi")` is asserted to refuse it. `tests/test_assess_clients.py`
invokes `assessment.entrypoints`. `tests/test_check_compatibility_matrix.py`
treats the 2026-08-22 matrix and readback as superseded history. Their
successor, `docs/evidence/2026-09-22-unifi-authored-cut.md`, is current and is
not a matrix. Citations of the retired matrix outside the evidence directory
say so in the link text.

`tests/test_unifi_readme.py` asserts that a resynchronization cannot run,
because that is what used to be able to replace the portable README.

## Rule

Deleting a provenance manifest means the synchronizer tests need their own
derived descriptor, and the old matrix stays a superseded document. Do not
invent a new matrix so a version binding stays green.
