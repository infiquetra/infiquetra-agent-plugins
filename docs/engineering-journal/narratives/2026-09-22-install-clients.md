# Install this catalog on each harness

Date: 2026-09-22
Author: Grok (custody-move unit U5, branch `mg/installer`)
Related entries:

- [Decision: the catalog installer](../DECISIONS.md)
- [Learning: a marketplace name is not a source](../LEARNINGS.md)
- [Runbook](../../runbooks/install-clients.md)
- [Custody-move plan](../../plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md)

## Context

Unit U5 is the script that points every harness on this machine at this
repository. The brief said to make the placement calls and record them. This
file is that record. The compatibility matrices and
`scripts/assess_clients.py` already say how each client places, discovers, and
loads a package. The script reuses those commands. It does not re-derive them,
and it does not add a placement the evidence does not support.

## Narrative

**Codex is unsupported, on purpose.** `codex plugin marketplace add` accepts a
local path or a git URL, and the help text is not the format. The marketplaces
Codex already has configured are loaded from
`.agents/plugins/marketplace.json`. Each plugin directory in those marketplaces
has `.codex-plugin/plugin.json` with a skills path and
`interface.defaultPrompt`. The dedicated Codex repository's own validator
rejects an active plugin that also contains `.claude-plugin`. Every
Claude-installable package in this catalog contains `.claude-plugin` and none
of them contain `.codex-plugin`. Writing `com.infiquetra.codex/marketplace.json`,
or writing `.agents/plugins/marketplace.json` that points at these packages,
would claim a Codex plugin the bytes are not. The script prints that reason and
does not create either file. `infiquetra-codex-plugins` is left as the Codex
marketplace. The three matrices already record the same refusal: marketplace
add of the package root fails because there is no supported manifest, and load
stays blocked on that adapter rather than on a package defect.

**Claude does not get a second marketplace entry.** The name
`infiquetra-agent-plugins` is registered as a directory source. The script reads
`~/.claude/plugins/known_marketplaces.json` and, only if that file has no
entry, `extraKnownMarketplaces` in `~/.claude/settings.json`. If the name is
present, it does not run `claude plugin marketplace add` again, and it does not
rewrite the registered path to the checkout that invoked the script. A worktree
and the primary checkout are different directories of the same repository.
Retargeting would make every already-installed plugin follow the worktree.
Install commands are still `claude plugin install <name>@infiquetra-agent-plugins`
for names listed in `.claude-plugin/marketplace.json`. A package that has a
`plugin.json` but is not in that file gets no install command. Readback
requires the install record, an enabled flag in `~/.claude/settings.json`, and
a registered directory equal to this checkout. A disabled install is reported
as elsewhere, not as absent, because the exit status is defined as absence.
The matrices' session-scoped `--plugin-dir` placement is how an assessment
proves load. It is not an install.

**Cursor uses the git URL, via `cursor-agent`.** `cursor` on `PATH` is the
editor. The marketplace subcommand is `cursor-agent plugin marketplace add`,
and its only source argument is a git URL. This repository's URL is
`https://github.com/infiquetra/infiquetra-agent-plugins`. The matrices called
that a distribution limit because a local directory cannot be added. The
repository is on GitHub, so the installer uses the URL rather than recording
Cursor unsupported. Readback lists plugin names in the cached marketplace file
under `~/.cursor/plugins/marketplaces/github.com/infiquetra/infiquetra-agent-plugins/`.
A second add is skipped when that cache already has a manifest. Removal of the
old marketplace uses the same command with the old repository's URL, and only
when that cache exists.

**Qwen, Grok, and Agy install the package directory.** Qwen's installer exits
without installing when stdin does not answer, so the script sends `y`, the
same confirmation the assessment sends. It then sets `source` on
`.qwen-extension-install.json` to the package directory and `type` to `local`,
keeping any other keys the client wrote. The directory path, not the GitHub
URL, is the source, because two checkouts of this repository share the URL and
readback has to tell them apart. Grok's command is `grok plugin install <dir>
--trust`. Readback uses `~/.grok/installed-plugins/registry.json` and does not
invent a second source file; Grok writes the source itself. Agy's command is
`agy plugin install <dir>`, which lands in `~/.gemini/config/plugins/<name>/`.
Agy does not record a source the readback can trust, so the script writes
`~/.gemini/config/plugins/.infiquetra-install.json`. Without that file a
successful install could never be classified as from this catalog. If the
directory is already there and the sidecar does not name this checkout, the
install is skipped. Those unsourced directories are where the Antigravity
packages already live, and the installer is not allowed to replace them.

**OpenCode follows the manifest that is already on the machine, not the
assessment's copy.** The assessment copies skill units into `~/.agents/skills`
because that is the auto-loaded directory it can prove under an isolated home,
and OpenCode has no install command for it. The Infiquetra install already in
use records symlinks in `~/.config/opencode/.infiquetra-plugins.json` with
schema `infiquetra-opencode-install.v1`. The script writes that same shape and
links into `~/.config/opencode/skills/`. It does not retarget a link that
already points somewhere else, which is what keeps
`infiquetra-opencode-plugins` installed.

**Gemini and Muse use the commands the assessment ran, and a manifest so
readback can tell our copies from anyone else's.** Gemini is `gemini skills
link <skill>` with `y` on stdin. The client's `--consent` flag also skips the
prompt, and it was not what the matrices ran, so the script does not switch to
it. Muse is `muse skills install <skill> --scope user`. Both record
`target` and `link` the same way OpenCode does. A destination that already
exists and is not ours is skipped, not overwritten.

**Hermes is a symlink, not a copy and not `hermes skills install`.** That
install subcommand takes a registry identifier or an HTTP URL. The assessment
therefore copied into `~/.hermes/skills/`. The profile already loads at least
one symlink there, so a symlink is a placement the client tolerates, and it is
what the brief asked for when the client tolerates one. `hermes skills
uninstall` is documented as removing a hub-installed skill, so legacy removal
does not call it. Removal unlinks or deletes only the destination a manifest
we wrote names, and only when that manifest's target is the old repository. A
symlink's target is not deleted. An unsourced directory is not deleted.

**Legacy removal keys off the recorded URL, never the marketplace name.**
Claude's `infiquetra-plugins` entry is the old git URL. Agy's marketplace of
the same name records `infiquetra/infiquetra-antigravity-plugins`. Deleting by
name would remove the dedicated Antigravity install. The script removes a
Claude marketplace only when its source URL is the old repository, a Grok or
Qwen entry only when its recorded source is that URL, a Cursor cache only when
the cache directory is that repository, and a Muse or Hermes copy only when
our manifest says so. Dedicated repositories are filtered out before the
legacy check.

**The real-binary rule is the refusal, not a search.** Grok and Agy are
started by name from `PATH`. Against a real home the wrapper finds its own
binary. `--binary` is accepted, and it is refused when the path is the same
file as the launcher on `PATH`, which is the failure
`assess_clients.resolve_real_binary` exists to prevent. The script does not
guess which other file of the same name is the real executable.

## Outcome

`scripts/install_client.py` plans all ten clients, reads their state back, and
removes only proven legacy placements. Codex stays unsupported until a package
in this catalog actually ships a Codex adapter. No client was installed by
this unit: the default is a dry run, and `--execute` was not run against the
operator's home.

## References

- `scripts/install_client.py`
- `tests/test_install_client.py`
- `docs/runbooks/install-clients.md`
- `scripts/assess_clients.py` (`CLIENT_PLANS`)
- `docs/evidence/2026-08-22-unifi-compatibility-matrix.md`
- `docs/evidence/2026-08-30-mission-control-compatibility-matrix.md`
- `docs/evidence/2026-08-27-agent-launcher-compatibility-matrix.md`
