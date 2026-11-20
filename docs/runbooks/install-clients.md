# Runbook: place this catalog on each harness

**Version 1.4.0** · Adopted 2026-09-22

Amendments:

- 1.1.0, 2026-09-22: idempotent placement, `not-applicable` readback, and
  continuing past failures under `--client all`.
- 1.2.0, 2026-10-14: Muse marketplace staging, source-proven migration and strict
  JSON verification, including the issue #237 code-review repairs.
- 1.3.0, 2026-11-19: harness installation tiers, retired Qwen and Gemini CLI
  targets, and provenance-gated `--prune-retired` (issue #334).
- 1.3.1, 2026-11-19: closeout upgrade order after retired-placement pruning
  (issue #336).
- 1.4.0, 2026-11-20: reusable multi-client selection and scoped retired pruning
  for staged rollouts.


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
[agent-launcher, superseded 2026-10-14](../evidence/2026-10-04-agent-launcher-compatibility-matrix.md)).
The script does not invent a second way to put a package where a client looks.

`--client` is required. Pass one harness, `all`, or several names. A comma-separated
list (`--client grok,opencode,muse`) and repeated flags
(`--client grok --client opencode --client muse`) combine, keep the order given,
and drop a repeated name. `all` cannot be combined with an explicit name, and a
blank item (`--client grok,` or `--client ""`) is rejected. The catalog root is
the checkout that contains the script; `--catalog` overrides it. Packages default
to every `plugins/<name>/` that has a `plugin.json`.
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

The process exits 1 when any applicable package is absent. For clients other
than Muse, an installation from elsewhere is reported without failing solely
for its source. A package a client cannot install is `not-applicable`, which
does not fail the run. Skill clients (OpenCode, Hermes) report
`not-applicable (no skills)` for packages without skill units; every client
reports `not-applicable (library)` for `fleet-core`. A lean harness reports a
package outside its default set as `not-applicable (tier)`, which also exits 0.

Muse's check also fails for a source or registration outside the requested
staging directory, a disabled or invalid plugin, diagnostics, an unavailable
selection, skipped Infiquetra entries, or a selected standalone skill that
collides with a plugin. These checks establish that the selected bundles came
from this catalog's projection and can be loaded without duplicate shortcuts.

For clients other than Muse, placing a package is idempotent. Muse re-stages
and refreshes selected bundles so source changes reach the installed cache. Before running the client's own install
command, the script reads back that client's own state the same way `--check`
does. A package already `installed-from-catalog` is skipped with a message
naming that; nothing is re-run, so a client whose install command refuses a
duplicate (Claude Code, Grok, Agy, Cursor) does not fail on a re-run
after a partial install, and a symlink or copy client leaves an
already-correct placement alone. A package `installed-from-elsewhere` is also
skipped, naming the other source, and is not replaced in the same run; the
message says to run `--uninstall-legacy --execute` first when that source is
the old `infiquetra-claude-plugins` repository or marketplace.

`--client all`, and any explicit list of more than one harness, does not stop
at the first client or package that fails to plan or place. Every failure is
recorded and printed at the end, execution continues with the next package and
client, and the process exits 1 with a summary if anything failed. A single
named `--client` keeps the original fail-fast behavior: a planning error such
as a missing marketplace file stops that run immediately with the error's own
exit code. Each harness in a list still uses its own tier, so a lean seat in
the same run as a full seat skips packages outside that lean default.

`--uninstall-legacy` removes a placement only when the client's own record says
the bytes came from `infiquetra/infiquetra-claude-plugins`. A directory with no
source record is left in place. These three repositories are never removed:
`infiquetra-codex-plugins`, `infiquetra-opencode-plugins`,
`infiquetra-antigravity-plugins`. For clients other than Muse it is a standalone removal run: pair it with
a plain `--execute` afterward to place the package fresh from this catalog
once the old placement is gone.

## Installation tiers

`schemas/harness-installation.json` names each harness. A port descriptor's
`installation.tiers` (schema version 5) says which tiers install that package.
The full tier is Claude Code, Codex, OpenCode, Agy, and Hermes, and it installs
every active package. OpenCode and Hermes stay on the full tier. The lean tier
is Cursor Agent, Muse, and Grok. A lean run installs `reviews`, `plan`, and
`investigate` unless `--package <name>` or `--profile full` is passed.

`--check` on a lean harness reports every other active package as
`not-applicable (tier)`. That line does not fail the run.

## Retired client targets

`--client qwen` and `--client gemini` are rejected. Qwen was retired on
2026-10-17 in favor of claude-qwen. Gemini CLI has been unassessed since
2026-10-04, when Agy replaced it. Agy still reads `~/.gemini`; that path is
Agy, not a Gemini CLI target. Historical compatibility matrices keep the
roster they were recorded with, including Qwen from 2026-10-04 and Gemini CLI
on earlier records.

## Prune retired placements

`--prune-retired` removes placements of the eight retired packages (`saga`,
`orchestrate`, `agy`, `codex`, `house-style`, `hermes-profile-evolution`,
`voice`, `redis-channel`) and the fifteen former `plugins/saga/skills/`
symlinks. A placement is removed only when its recorded source is this catalog
or `infiquetra/infiquetra-claude-plugins`, or when a symlink target resolves
into this checkout's retired tree, including a dangling link. The live symlink
wins over a stale sidecar: a link the operator has retargeted outside that
ownership is left in place. A directory named `infiquetra-claude-plugins` is
the legacy repository only when its git origin is that repository, or when no
git checkout encloses it and the path continues `plugins/<name>`. Sidecar entries
in `~/.config/opencode/.infiquetra-plugins.json` and
`~/.hermes/.infiquetra-skills.json` follow the same rule. Foreign and
unsourced entries stay. The default is a dry-run. Pass `--execute` to unlink.
Do not combine it with `--check` or `--uninstall-legacy`.

An explicit `--client` list prunes only the harnesses named in that list.
`qwen` and `gemini` are accepted in the list when `--prune-retired` is set, and
they are rejected in every other mode, including `--dry-run` and `--check`.
`--client all --prune-retired` still prunes the eight active harnesses plus
Qwen and Gemini CLI. `--agy-account company` applies only when `agy` is the
sole client. With `--prune-retired`, that account cleans the company Gemini
directory (`<company-root>/gemini`) and leaves the personal `~/.gemini` tree
in place. Company install `--execute` stays refused, because that path would
invoke the vendor binary against the personal account. Company prune
`--execute` edits the company directory directly.

## Staged multi-client rollout

Roll a subset of harnesses out, then the rest, without a later phase rewriting
the earlier one. Phase 1 is the lean Grok seat plus the full OpenCode and Muse
seats. Phase 2 is Claude, Codex, Agy, and Hermes, including removal of the
retired Qwen and Gemini CLI placements and a separate company Agy prune.

Phase 1 prints the plan, prunes only those three harnesses, places them, and
reads them back:

```bash
python3 scripts/install_client.py --client grok,opencode,muse --prune-retired --dry-run
python3 scripts/install_client.py --client grok,opencode,muse --prune-retired --execute
python3 scripts/install_client.py --client grok,opencode,muse --execute
python3 scripts/install_client.py --client grok,opencode,muse --check
```

The same three names can be split across flags:

```bash
python3 scripts/install_client.py --client grok,opencode --client muse --check
```

Phase 2 prunes Claude, Codex, Agy, Hermes, Qwen, and Gemini, then places and
checks the four active harnesses. Grok, OpenCode, and Muse are absent from
both commands, so their placements stay as Phase 1 left them.

```bash
python3 scripts/install_client.py --client claude,codex,agy,hermes,qwen,gemini --prune-retired --dry-run
python3 scripts/install_client.py --client claude,codex,agy,hermes,qwen,gemini --prune-retired --execute
python3 scripts/install_client.py --client claude,codex,agy,hermes --execute
python3 scripts/install_client.py --client claude,codex,agy,hermes --check
```

Company Agy is its own pair of commands. Point `--agy-company-home` at the
company root whose `gemini` directory should be cleaned:

```bash
python3 scripts/install_client.py --client agy --agy-account company --agy-company-home <company-root> --prune-retired --dry-run
python3 scripts/install_client.py --client agy --agy-account company --agy-company-home <company-root> --prune-retired --execute
```

`--check` on a multi-client list reads every named harness, including the
Cursor whole-repository line when `cursor` is one of the names, and exits 0
when each named harness satisfies its tier.

## Closeout upgrade

A workstation that still has pre-3.0 placements moves to this catalog in four
separate runs. The first prints the prune plan and changes nothing. The second
unlinks catalog-owned retired placements, including the former
`plugins/saga/skills/` symlinks. The third places the current catalog: every
active package on a full harness, and `reviews`, `plan`, and `investigate` on
a lean harness. The fourth reads every harness back and exits 0 when every
applicable package is present. `--prune-retired` does not install, and a plain
`--execute` does not prune, so the steps stay in this order.

```bash
python3 scripts/install_client.py --client all --prune-retired --dry-run
python3 scripts/install_client.py --client all --prune-retired --execute
python3 scripts/install_client.py --client all --execute
python3 scripts/install_client.py --client all --check
```

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
claude plugin marketplace add infiquetra/infiquetra-agent-plugins
claude plugin install <name>@infiquetra-agent-plugins
```

The marketplace is registered from the GitHub repository, not from the local
checkout, so the installed plugins follow `main` on GitHub rather than whatever
branch or uncommitted work the checkout holds. Claude Code records it as
`{"source": "github", "repo": "infiquetra/infiquetra-agent-plugins"}`. The
marketplace refreshes itself when Claude Code starts (its `autoUpdate`
setting), so a merged release reaches the installed plugins without a pull.

The marketplace add is skipped when `infiquetra-agent-plugins` is already
present in `~/.claude/plugins/known_marketplaces.json` (or, if that file has no
entry, in `extraKnownMarketplaces` in `~/.claude/settings.json`). The existing
registration is not rewritten to point somewhere else.

`--check` reads `~/.claude/plugins/installed_plugins.json` and
`enabledPlugins` in `~/.claude/settings.json`. A package is from this catalog
only when the install id is `<name>@infiquetra-agent-plugins`, the id is
enabled, and that marketplace's registration is this catalog. Any of these
registrations counts as this catalog:

- a `github` source whose repo is `infiquetra/infiquetra-agent-plugins`
  (compared without regard to case);
- a `git` or `url` source whose URL is this repository, as
  `https://github.com/infiquetra/infiquetra-agent-plugins` with or without
  `.git`, or `git@github.com:infiquetra/infiquetra-agent-plugins.git`;
- a `directory` source whose path resolves to this checkout, so an older local
  registration still reads correctly.

Any other registration is reported as elsewhere, naming the path, URL or repo
it points at. A disabled install is reported as elsewhere. A package that is
not listed in the marketplace file is not given an install command.

To test plugin changes that are not merged yet, start a session with
`claude --plugin-dir <checkout>/plugins/<name>`. The installed copy only
carries what is on GitHub.

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

`cursor-agent` registers the whole GitHub repository as one marketplace. There
is no per-package Cursor install flag. The lean tier changes which packages
`--check` requires and does not split that registration. `--check` prints
`cursor marketplace whole-repository` before the per-package lines. A package
outside the lean default is `not-applicable (tier)` even when the cached
marketplace lists it. `--profile full` drops that tier exclusion and still
issues only the one marketplace registration.

`--check` reads that cache, and the same path for
`infiquetra-claude-plugins`. A package named in this repository's cached
marketplace file is from the catalog. A package named only in the old cache is
elsewhere. Cursor's marketplace command accepts a git URL and not a local
directory; that is the distribution limit the matrices recorded, and this
repository is on GitHub, so the limit is not a reason to call the client
unsupported.

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

## Muse

The Muse **projection** is a generated directory of copied packages with their
manifests transformed into the Claude-compatible shapes Muse can load. It
excludes competing root and Codex manifests and unsupported Claude declarations.
The source packages remain unchanged. A full-tier run selects every package
`muse_applicable_packages` returns. A lean run selects `reviews`, `plan`, and
`investigate`, and does not sweep the other installed plugins. `--package` and
`--profile full` restore the wider selection.

Planning invokes no Muse command and performs no staging. Execution stages at
`<catalog>/build/muse-marketplace` (or `--staging-dir`) and registers it as
`infiquetra-claude-plugins`. This compatibility alias points to this repository's
projection; it does not select the retired repository. The raw multi-manifest
checkout cannot substitute for the projection.

```text
muse plugins marketplace add <staging directory>
muse plugins install <name>@infiquetra-claude-plugins
```

Muse 1.4.7 requires a name on marketplace add. A **compatibility retry** means
retrying that specific parser refusal with
`muse plugins marketplace add infiquetra-claude-plugins <staging directory>`.
This version has one installed user-plugin registry keyed by bare plugin id;
marketplace installs cannot select project scope. `--scope project` is refused
before planning or mutation. Installs omit `--scope`; user-plugin removal starts
with `muse plugins uninstall <name>@<marketplace> --scope user`, and retries the
1.4.7 unsupported-command refusal as `muse plugins remove <bare-id>`. A failed
retry prints Muse's error and exits 1. Runtime failures are never retried as
parser compatibility cases.

The staging directory must belong to the current user, have no group/other
write permission, and be a real directory rather than a symlink. First staging
requires an absent or empty directory and writes `.infiquetra-muse-staging` to
record custody. An existing non-empty unmarked directory is refused. A full
run removes stale entries only when both the marker and previous generated
marketplace identify them as owned. Foreign entries survive and are never
listed. A partial `--package` run preserves previously owned unselected bundles.

Explicit `--client muse --package fleet-core` or `--package house-style` is an
error before staging. Under `--client all`, these are reported as Muse
`not-applicable` while other clients continue. `--package` is repeatable.

When the compatibility registration points to a different staging directory,
the installer first removes selected plugins proven to belong to that old
registration, then removes and adds the registration and reinstalls the selected
bundles. Muse retains installed records when a registration is removed, so
uninstalling first is necessary. Unselected installed plugins remain untouched.
A registration already pointing to the requested stage is refreshed with
`muse plugins marketplace update infiquetra-claude-plugins`.

```bash
python3 scripts/install_client.py --client muse --dry-run
python3 scripts/install_client.py --client muse --uninstall-legacy --execute
python3 scripts/install_client.py --client muse --check
python3 scripts/install_client.py --client muse --package unifi --staging-dir build/muse-marketplace --execute
```

For Muse, `--uninstall-legacy --execute` migrates and installs in one run. Legacy
registrations are identified by their source URL or checkout path, including
`infiquetra` and `claude-code-Marketplace` when they point to the retired
`infiquetra-claude-plugins` repository. Installed source paths are correlated
with those registrations and available-list entries. Only selected legacy
plugins are removed; a legacy registration is removed when no installed records
still depend on it. A filtered migration preserves a registration needed by
unselected plugins. Unrelated marketplace sources remain untouched.

Migration also removes selected redundant user-scope skills whose source is
proven by `~/.config/muse/.infiquetra-skills.json` or
`~/.config/muse/skills/.muse/lock.json`, using
`muse skills uninstall <name>`. Conflicting or missing provenance
preserves the copy. A drained installer sidecar is removed. Without the legacy
flag, plugin refresh preserves standalone skills. The internal `plan_uninstall`
API removes legacy placements only; the CLI migration's `plan_install` composes
that cleanup with staging and installation.

`--check` performs no staging, installation or cleanup. It reads installed and
available JSON and the marketplace registry. The registration must resolve to
the requested staging directory, and every selected installed source must
resolve to `<staging directory>/plugins/<name>`. A different registration or
source is `installed-from-elsewhere` and exits 1. Selected records must be
enabled, valid and have `diagnostics == []`; selected plugins must be available,
and the Infiquetra marketplace must have no skipped entries. Unrelated
marketplace diagnostics or skips do not fail this check. Every selected skill
name is checked for a directory or symlink under `~/.config/muse/skills`; a
collision fails with its path and leaves the placement intact. Unselected
packages' skills do not fail a filtered check.

`assess_clients.py` stages and installs inside an isolated home, validates the
projection, discovers installed and available JSON, and inspects the bare plugin
id. Load validation must return `valid == true` and `diagnostics == []` before
invocation can use the reported installed cache path. Source symlinks retain
their targets until the staging containment guard checks them. Both scratch and
staged package bytes are fingerprinted before and after the run; changed bytes
invalidate the row. The [client inventory](../compatibility/client-assessment.json)
describes the current plan. Parent #234 retains live workstation and session
acceptance; isolated checks do not close that gate.

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
