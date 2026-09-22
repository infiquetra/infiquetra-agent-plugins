# Runbook: place this catalog on each harness

**Version 1.1.0** · Adopted 2026-09-22 · Amended 2026-09-22 to make placement
idempotent, add the `not-applicable` readback status, and make `--client all`
continue past a failing client or package

This is the operator checklist for
[`scripts/install_client.py`](../../scripts/install_client.py). The calls behind
it are written up in
[the installer narrative](../engineering-journal/narratives/2026-09-22-install-clients.md)
and the
[decision](../engineering-journal/DECISIONS.md).
Placement follows
[`scripts/assess_clients.py`](../../scripts/assess_clients.py) and the three
compatibility matrices
([UniFi, superseded 2026-09-22 and kept as historical context](../evidence/2026-08-22-unifi-compatibility-matrix.md),
[Mission Control, superseded](../evidence/2026-08-30-mission-control-compatibility-matrix.md),
[agent-launcher](../evidence/2026-08-27-agent-launcher-compatibility-matrix.md)).
The script does not invent a second way to put a package where a client looks.

The catalog root is the checkout that contains the script. `--catalog` overrides
it. Packages default to every `plugins/<name>/` that has a `plugin.json`.
Nothing is installed, linked, or deleted unless `--execute` is passed. The
default, and `--dry-run`, print every command and file operation.

```bash
python3 scripts/install_client.py --client all --dry-run
python3 scripts/install_client.py --client all --check
python3 scripts/install_client.py --client claude --execute
python3 scripts/install_client.py --client all --uninstall-legacy
```

`--check` prints one line per package:

- `installed-from-catalog`
- `installed-from-elsewhere (<source>)`
- `not-applicable (<reason>)`
- `absent`

The process exits 1 when any package is absent. A package installed from
somewhere else is not an absence, and neither is a package a client cannot
hold at all: a skill-scoped client (OpenCode, Gemini CLI, Muse, Hermes)
reports `not-applicable (no skills)` for a package with no skill units, and
every client reports `not-applicable (library)` for `fleet-core`, which has no
per-package Claude packaging manifest and is bundled into other packages at
build time rather than installed on its own.

Placing a package is idempotent. Before running the client's own install
command, the script reads back that client's own state the same way `--check`
does. A package already `installed-from-catalog` is skipped with a message
naming that; nothing is re-run, so a client whose install command refuses a
duplicate (Claude Code, Qwen, Grok, Agy, Cursor) does not fail on a re-run
after a partial install, and a symlink or copy client leaves an
already-correct placement alone. A package `installed-from-elsewhere` is also
skipped, naming the other source, and is not replaced in the same run; the
message says to run `--uninstall-legacy --execute` first when that source is
the old `infiquetra-claude-plugins` repository or marketplace.

`--client all` does not stop at the first client or package that fails to
plan or place. Every failure is recorded and printed at the end, execution
continues with the next package and client, and the process exits 1 with a
summary if anything failed. A single named `--client` keeps the original
fail-fast behavior: a planning error such as a missing marketplace file
stops that run immediately with the error's own exit code.

`--uninstall-legacy` removes a placement only when the client's own record says
the bytes came from `infiquetra/infiquetra-claude-plugins`. A directory with no
source record is left in place. These three repositories are never removed:
`infiquetra-codex-plugins`, `infiquetra-opencode-plugins`,
`infiquetra-antigravity-plugins`. It is a standalone removal run: pair it with
a plain `--execute` afterward to place the package fresh from this catalog
once the old placement is gone.

`--binary <client>=<path>` replaces the executable on `PATH`. A path that is the
same file as that launcher is refused. Pointing a wrapper at itself is how the
launcher re-executes until the machine runs out of processes. Omit the flag to
invoke the launcher by name, which is what works against a real home.

A skill-scoped client installs one destination per skill directory name. Two
packages that ship the same skill name are an error. A package with no skill
units is skipped on install and reported `not-applicable (no skills)` on
check.

## Claude Code

Command, for each name listed in `.claude-plugin/marketplace.json`:

```text
claude plugin marketplace add <catalog>
claude plugin install <name>@infiquetra-agent-plugins
```

The marketplace add is skipped when `infiquetra-agent-plugins` is already
present in `~/.claude/plugins/known_marketplaces.json` (or, if that file has no
entry, in `extraKnownMarketplaces` in `~/.claude/settings.json`). The existing
registration is not rewritten to point at a different checkout.

`--check` reads `~/.claude/plugins/installed_plugins.json` and
`enabledPlugins` in `~/.claude/settings.json`. A package is from this catalog
only when the install id is `<name>@infiquetra-agent-plugins`, that marketplace's
directory source is this checkout, and the id is enabled. A disabled install is
reported as elsewhere. A package that is not listed in the marketplace file is
not given an install command.

Known limitation, from the matrices: user-scope install needs the marketplace
file. Session `--plugin-dir` is how the assessment proved the package loads. It
is not how this script installs.

## OpenAI Codex

Codex CLI 0.155.1 installs this checkout with two commands. The marketplace
name is the `name` in `.agents/plugins/marketplace.json`, which the generator
writes as `infiquetra-agent-plugins`.

```text
codex plugin marketplace add <catalog>
codex plugin add <name>@infiquetra-agent-plugins
```

`.agents/plugins/marketplace.json` sits at the catalog root, and each plugin
directory carries `.codex-plugin/plugin.json`. `scripts/sync_codex_packaging.py`
writes both. The CLI looks at those paths and not at a file under
`com.infiquetra.codex/`.

The marketplace add records `[marketplaces.infiquetra-agent-plugins]` in
`~/.codex/config.toml` with `source_type = "local"` and `source` set to this
checkout. It does not install plugins. The plugin add records
`[plugins."<name>@infiquetra-agent-plugins"]` with `enabled = true`.

The marketplace add is skipped when that name is already registered. The
existing registration is not rewritten to point at a different checkout. When
the name points somewhere else, the plugin add is skipped too: `codex plugin
add` takes `name@marketplace` and installs whatever source that name currently
has.

`--check` reads `~/.codex/config.toml`. A package is from this catalog only
when `<name>@infiquetra-agent-plugins` is `enabled = true` and the marketplace
`source` resolves to this checkout. A disabled flag is reported as elsewhere.
A package enabled under another marketplace, including
`infiquetra-codex-plugins`, is elsewhere and is not an absence.

`--uninstall-legacy` removes a `[marketplaces.*]` table whose `source` is the
old repository, by running `codex plugin marketplace remove <name>`. It does
not remove `infiquetra-codex-plugins`. The script runs those Codex commands
only when `--execute` is passed. The dedicated Codex repository is not
modified.

## Cursor Agent

The binary on `PATH` is `cursor-agent`, not `cursor`.

```text
cursor-agent plugin marketplace add https://github.com/infiquetra/infiquetra-agent-plugins
```

The add is skipped when
`~/.cursor/plugins/marketplaces/github.com/infiquetra/infiquetra-agent-plugins/`
already contains a `.claude-plugin/marketplace.json`.

`--check` reads that cache, and the same path for
`infiquetra-claude-plugins`. A package named in this repository's cached
marketplace file is from the catalog. A package named only in the old cache is
elsewhere. Cursor's marketplace command accepts a git URL and not a local
directory; that is the distribution limit the matrices recorded, and this
repository is on GitHub, so the limit is not a reason to call the client
unsupported.

## Qwen

```text
qwen extensions install <package directory>
```

Standard input is `y`. With no answer the installer lists skills and exits
without installing, which is the quirk the assessment records.

Afterwards the script sets `source` to that package directory and `type` to
`local` in `~/.qwen/extensions/<name>/.qwen-extension-install.json`, and leaves
every other key the client wrote. `--check` reads that `source`.

`--uninstall-legacy` runs `qwen extensions uninstall <name>` when `source` is
the old repository. A directory with no install file is refused.

## Grok

```text
grok plugin install <package directory> --trust
```

`--trust` is what skips the confirmation prompt. `--check` reads
`~/.grok/installed-plugins/registry.json`. An entry is from this catalog when
`marketplace.source_url_or_path` or `kind.source_path` is this checkout or this
repository's GitHub URL.

`--uninstall-legacy` runs `grok plugin uninstall <name> --confirm` for a plugin
whose recorded source is the old repository. `--confirm` is the client's own
switch for skipping the multi-plugin prompt. A source under a dedicated
repository is skipped.

## OpenCode

No client command. The assessment copied skill units into `~/.agents/skills`
because that is the documented auto-loaded directory under an isolated home.
The install already on this machine records symlinks in
`~/.config/opencode/.infiquetra-plugins.json` (`schema`
`infiquetra-opencode-install.v1`) whose `link` is under
`~/.config/opencode/skills/`. This script follows that file: one symlink per
skill unit, and one new `links` entry. An existing link that points somewhere
else is not retargeted, so the dedicated OpenCode repository's links stay put.

`--check` resolves the symlink. A real directory is from this catalog only when
the manifest's `target` is the skill unit in this checkout.

`--uninstall-legacy` unlinks a manifest entry whose `target` is the old
repository, and does not delete the target. An unsourced directory is refused.

## Gemini CLI

```text
gemini skills link <skill directory>
```

Standard input is `y`. Closed stdin hangs this command instead of declining,
which is why the assessment supplies the confirmation and a deadline. The
script does the same. It then records the skill in
`~/.gemini/.infiquetra-skills.json`.

`--check` reads `~/.gemini/skills/<skill>`. A symlink must resolve to the skill
unit. A copy counts as this catalog only when the manifest names that unit.

`--uninstall-legacy` runs `gemini skills uninstall <name>` and then removes the
destination when the manifest says the old repository. An unsourced directory
is refused.

## Muse

```text
muse skills install <skill directory> --scope user
```

The client refuses the package root, so each skill unit is installed on its
own, as the assessment did. The script records the unit in
`~/.config/muse/.infiquetra-skills.json`. `--scope user` is what lands it in
`~/.config/muse/skills/`.

`--check` reads that directory plus the manifest.

`--uninstall-legacy` runs `muse skills uninstall <name>` for a manifest entry
whose target is the old repository, then removes a leftover copy under the
skills directory. An unsourced directory is refused. Muse has no record of
source of its own; without the manifest we wrote, the copy is not ours to
delete.

## Agy

```text
agy plugin install <package directory>
```

The copy lands in `~/.gemini/config/plugins/<name>/`. Agy does not write a
source field the readback can trust, so the script records one in
`~/.gemini/config/plugins/.infiquetra-install.json`. `--check` requires both
the directory and a source that is this checkout. If that directory already
exists and the sidecar does not say it came from this checkout, the install
command is not run. An unsourced directory is how the Antigravity packages
sit in the same folder, and replacing it would delete them.

The marketplace named `infiquetra-plugins` in
`~/.gemini/config/plugins/known_marketplaces.json` can point at
`infiquetra/infiquetra-antigravity-plugins`. The name is not the old
repository. `--uninstall-legacy` skips that entry. It runs
`agy plugin uninstall <name>` only when the sidecar manifest's source is the
old git URL. An installed directory with no sidecar entry is refused.

## Hermes

No client command. `hermes skills install` takes a registry identifier or an
HTTP URL, not a local directory, which is why the assessment copied. The live
profile already loads a symlink under `~/.hermes/skills/`, so this script
symlinks each skill unit and records it in `~/.hermes/.infiquetra-skills.json`.
`hermes skills uninstall` removes a hub-installed skill, so it is not used on
these copies.

`--check` resolves the symlink, or trusts the manifest when the destination is
a real directory we recorded.

`--uninstall-legacy` removes the destination named by a manifest entry whose
target is the old repository. A symlink is unlinked and its target is not
deleted. A real directory is removed only when it sits directly in
`~/.hermes/skills/`. An unsourced copy is refused. The assessment's rule still
holds for a live run of the assessment itself: that run stays on an isolated
home and does not write the operator profile.
