# Codex packaging for this catalog

Date: 2026-09-22
Author: Grok (custody-move unit U5b, branch `mg/codex-pkg`)
Related entries:

- [Decision: Codex packaging sits at the repository root](../DECISIONS.md)
- [Learning: Codex accepts a Claude manifest beside its own](../LEARNINGS.md)
- [Runbook](../../runbooks/install-clients.md)
- [Custody-move plan](../../plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md)

## Context

Unit U5 recorded Codex as unsupported. The reason it gave was that a Codex
plugin directory must not also contain `.claude-plugin`, and this catalog's
packages do. This unit checked that claim against the CLI on this machine
and generated the files the CLI actually loads. The worktree is
`/Users/jefcox/workspace/infiquetra/mg-codex-pkg` on branch `mg/codex-pkg`.
The dedicated repository `infiquetra-codex-plugins` was read and not
modified. `~/.codex/config.toml` was read and not modified.

## What was verified

Codex CLI 0.155.1, `codex plugin marketplace add --help`: the source is a
local path, `owner/repo[@ref]`, an HTTPS git URL, or an SSH git URL.
`codex plugin add --help`: the selector is `PLUGIN@MARKETPLACE`.

`~/.codex/config.toml` already has `[marketplaces.<name>]` tables with
`source_type` and `source`, and `[plugins."<name>@<marketplace>"]` tables
with `enabled`. `infiquetra-codex-plugins` is one of those marketplaces,
with `source_type = "git"` and
`source = "https://github.com/infiquetra/infiquetra-codex-plugins.git"`.

The OpenAI bundled marketplace and `infiquetra-codex-plugins` both keep
`.agents/plugins/marketplace.json` at the repository root. Each plugin
entry is `source.source = "local"`, `source.path = "./plugins/<name>"`,
`policy.installation = "AVAILABLE"`, `policy.authentication = "ON_INSTALL"`.
Each plugin directory has `.codex-plugin/plugin.json`. `skills`, when
present, is the string `./skills/`.

An installed copy of `google-cloud-developer` under
`~/.codex/plugins/cache/google-plugins/` contains both `.claude-plugin/` and
`.codex-plugin/`. Its Codex manifest has `skills`, `interface.displayName`,
`interface.shortDescription`, and `interface.category`. It has no
`interface.defaultPrompt`.

A probe used `CODEX_HOME=/tmp/codex-pkg-probe/home` so it could not write
`~/.codex`. The fixture checkout contained a Claude marketplace and a Codex
marketplace, and a plugin directory that contained both manifests, plus a
second plugin with no `skills` directory. `codex plugin marketplace add
<fixture> --json` exited 0 and wrote:

```toml
[marketplaces.infiquetra-agent-plugins]
source_type = "local"
source = "/private/tmp/codex-pkg-probe/repo"
```

`codex plugin list --available --json` listed both plugins, including the
one whose manifest had no `skills` and no `defaultPrompt`, and including
the one whose marketplace entry had no `category`. `installed` was empty
until `codex plugin add sample@infiquetra-agent-plugins --json`, which
wrote `[plugins."sample@infiquetra-agent-plugins"]` with `enabled = true`.
The sha256 of `~/.codex/config.toml` was
`5f3919da7a01db3dc6e40ada0ce5c7ee6920172b8b1868cffcc9af572a7588e1` before
and after that probe. The CLI resolved `/tmp` to `/private/tmp`, so a later
readback has to resolve both paths. A later dry-run of
`scripts/install_client.py --client codex --dry-run` printed the add
commands and left the config hash unchanged across that command. The
marketplace name `infiquetra-agent-plugins` is not in the config. The file's
hash had moved between the probe and that dry-run; this unit did not run a
Codex command against the default Codex home.

## Calls

The marketplace name is `infiquetra-agent-plugins`, the same name the Claude
marketplace already uses. It is not `infiquetra-codex-plugins`, because that
name is already the dedicated git marketplace in the operator's config.

`category` is kept when a previous marketplace entry has one, and is not
invented. The probe listed an entry that had none.

`interface.defaultPrompt` is omitted. It is a prompt, which is behaviour,
and the CLI listed a plugin that did not have one. `hooks` is omitted. The
CLI's bundled plugin scaffold says validation rejects that field, and a
hook body would be behaviour in a manifest that is only allowed to carry
paths.

`skills` is `./skills/` when the portable directory exists. It is
`./com.infiquetra.codex/skills/` only when the portable directory does not
and the adapter does. `mcpServers` is a path to
`com.infiquetra.codex/.mcp.json` only when that file exists. A `.mcp.json`
at the package root is not declared. No package in this tree has
`com.infiquetra.codex/` yet, so the generated manifests point only at
`./skills/` or, for `fleet-core` and `house-style`, at no skills path.

After this branch was rebased onto `origin/main`, UniFi's
`PROVENANCE.json` was already gone: the authoring commit deleted it.
The generated Codex manifest for UniFi therefore has nothing to classify.
`plugins/mission-control/PROVENANCE.json` is the package manifest that
still classifies every file. Its Codex manifest is `target-owned`. It has
no upstream counterpart, and a target-owned entry records no digest, so
regenerating the manifest does not look like tampering. The same rebase
added portable packages `agy`, `codex`, and `orchestrate`. The generator
was run again so the marketplace lists them. `codex` here is the delegation
package, not the CLI.

`interface.displayName` is the package name with hyphens spelled as words.
`interface.shortDescription` is the portable description, so the two cannot
drift. `developerName`, `brandColor`, and `capabilities` are not generated.
The probe's manifest did not need them.

The installer skips `plugin add` when the marketplace name is already
registered at a different source. `plugin add` has no path argument, so
running it would install that other source. Claude's installer still issues
`plugin install` in that case because that command is a separate record.
Codex's is not.

The root `README.md` still describes Codex distribution as an open
decision from the ten-client assessments. That prose was left in place.
Two counts in the same file were updated, from 72 to 73, because
`tests/test_mission_control_rule_audit.py` recomputes the Mission Control
package file count from disk and the generated Codex manifest is one more
file. Historical evidence that names an older UniFi file count was not
rewritten.

`scripts/check_repo.py` is one of the files
`MutationProofBindingTest` binds to a digest. Wiring the Codex check into
it requires a new proof document. Cycle 17 is left unedited. Cycle 18
records the new digest and the one mutation this unit graded: removing the
new call. The other graded files are carried forward. The other guards
inside `check_repo.py` were graded in cycle 17 against the previous bytes
and were not re-run here.

## What was not done

The operator's Codex config was not changed. `codex plugin marketplace add`
was not run against `~/.codex`. `infiquetra-codex-plugins` was not edited.
Nothing was merged.
