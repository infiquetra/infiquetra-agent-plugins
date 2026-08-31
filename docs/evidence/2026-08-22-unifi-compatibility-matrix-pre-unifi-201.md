<!-- matrix-status: superseded -->
<!-- superseded-by: 2026-08-22-unifi-compatibility-matrix.md -->
<!-- superseded-reason: The forty stage results describe portable package 2.0.0 at tree digest da46ca77..., before the re-synchronization from UniFi 2.0.1 replaced both client entrypoints and the upstream changelog. The shipped package is 2.0.1 and fingerprints to cafe8836..., so this record no longer identifies the tree it claims to describe. -->

# Ten-client compatibility matrix — portable UniFi package

This repository holds the proposed portable source catalog for Infiquetra Agent
Skills and Agent Plugins. One package in it, `plugins/unifi/`, was assembled as a
derived artifact from an upstream Claude Code plugin. This document records what
happened when that package was put in front of every coding-agent client
installed on the operator's machine, on 22 August 2026.

The point of the exercise is to learn which clients can consume a portable
package and which cannot, before anyone commits to a distribution path. It is a
survey, not a release gate.

## This is the second re-run, and what it replaces

Two earlier publications of this matrix are preserved as history, each retired
for a different reason:

1. [the superseded pre-repair record](2026-08-22-unifi-compatibility-matrix-pre-repair.md)
   assessed the package as originally assembled: 21 files, with both skill
   entrypoints aborting at import because the synchronization step had dropped
   `fleet_commons_shim.py` and no generated bundle had yet replaced it.
2. [`2026-08-22-unifi-compatibility-matrix-pre-resync.md`](2026-08-22-unifi-compatibility-matrix-pre-resync.md)
   assessed the repaired 23-file package, at tree digest `6e6b57c1…`, whose
   entrypoints run.

This document is the re-run against the package as it now ships. What moved
between the second publication and this one is a build artifact, not a client:
re-synchronizing the portable Fleet Core slice to release 0.25.1, at upstream
commit `ed72f439`, regenerated both
`skills/*/scripts/_bundled/retry_backoff.py` bundles and re-pinned
`plugins/unifi/PROVENANCE.json`. All three files live inside `plugins/unifi/`,
so the assessed tree changed. The file count did not: it is still 23 files, now
at tree digest `da46ca77…`.

**Every one of the forty stage results below was executed again against that
tree.** Nothing was carried forward on the assumption that it still held. What
the re-run produced is recorded in [Results](#results); the short version is
that no verdict changed and three recorded digests did.

The reason a build-artifact change forces a full re-run rather than an edit is
that this document is *bound* to the package it assessed: the file count and
tree digest recorded below are recomputed from `plugins/unifi/` on every
validation run and compared. See
[Binding, and what a superseded matrix may claim](#binding-and-what-a-superseded-matrix-may-claim).

## What this document is, and is not

**Coverage is mandatory; passing is not.** No unsupported or failing client
blocks completion. A client that could not load the package is recorded with its
reason and the assessment moves on. Nothing here was repaired, adapted, or
worked around: whether a failure warrants a fix, an adapter, a different
distribution path, or an explicitly unsupported status is a separate decision,
and it belongs to the operator.

**Every stage is recorded, including the ones that never ran.** Each client
carries four results — placement, discovery, load, invocation — even when an
early stage already failed. A row that stops at its first failure and reports a
single status can be counted as covered while proving nothing about whether the
package ever loaded. Ten rows are not ten assessments.

**This repository is public.** The record below carries client names, stage
results, counts, and digests. It carries no discovered inventory, no
site-identifying address or hostname, no hardware address, and no credential
value. Commands are recorded with their site-identifying arguments replaced by
placeholders. [`scripts/check_compatibility_matrix.py`](../../scripts/check_compatibility_matrix.py)
enforces all of that mechanically, because a rule that only prose states is a
rule that eventually gets broken.

The authoritative plan for this work is
[the portability pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md).

## How every client was assessed

The same four stages were run against every client, in the same order:

| Stage | What it asks |
|---|---|
| Placement | Can the package, or its portable skill units, be installed or placed where this client documents that it looks? |
| Discovery | Does the client's own inventory command enumerate what was placed? |
| Load | Does the client parse the placed definitions and hold them — resolved metadata, active state, no diagnostic — rather than merely list them? |
| Invocation | Does the safest meaningful credential-free, read-only entrypoint run, from the path this client resolved? |

Held identical across all ten:

- **Isolation.** Each client ran against its own empty home directory in a
  scratch area. No assessment read or wrote the operator's real client
  configuration. Every result therefore reflects a first-run install.
- **Credentials.** No client was authenticated and no controller credential was
  supplied at any stage. Every `UNIFI_` variable was removed from the
  environment before each invocation. Where a client demands credentials before
  it will report extension state, that stage is recorded blocked with the
  requirement named, not satisfied.
- **Network.** No controller call was made at any stage. The invocation stage
  runs the package's own entrypoint with its credential-free help action and no
  host argument, so no request leaves the machine. No mutating operation was
  invoked and no command passed a write confirmation.
- **The assessed copy is the shipped tree.** The package root handed to each
  client was a scratch copy of `plugins/unifi/`, and it was fingerprinted before
  the run: 23 files, `da46ca77…`, equal to the source tree.

Where a single client command yields both the enumeration and the resolved unit
definitions, that command is recorded for both discovery and load, and each
stage's evidence names the fact it draws from it.

## The status rubric

The plan fixes four statuses but does not define them, so they are defined here
and applied uniformly:

- **Works directly** — the client placed, discovered, and loaded the portable
  package, or its portable skill units, as shipped: no vendor-specific artifact
  added, no diagnostic raised.
- **Works through an adapter** — the client cannot consume the portable form as
  shipped, and its own tooling names the specific vendor artifact that would be
  required. This status identifies the path; it does not claim the path was
  proven, because building an adapter is remediation and out of scope here.
- **Unsupported** — the client has no extension mechanism that could accept this
  package in any form.
- **Failed** — a supported path existed, and the assessment could not get the
  package through it. The blocking cause is named in the row, and it may be the
  package or the client.

## Results

Eight of ten clients consumed the portable package or its skill units directly.

| Client | Version | Placement | Discovery | Load | Invocation | Status |
|---|---|---|---|---|---|---|
| Claude Code | 2.1.240 | executed | executed | executed | executed | works directly |
| OpenAI Codex | 0.149.0 | executed | executed | blocked | blocked | works through an adapter |
| Cursor Agent | 2026.08.11 | blocked | blocked | blocked | blocked | failed |
| Qwen | 0.21.15 | executed | executed | executed | executed | works directly |
| Grok | 1.0.5 | executed | executed | executed | executed | works directly |
| OpenCode | 1.18.18 | executed | executed | executed | executed | works directly |
| Gemini CLI | 0.44.1 | executed | executed | executed | executed | works directly |
| Muse | 0.2.1 | executed | executed | executed | executed | works directly |
| Agy | 1.1.18 | executed | executed | executed | executed | works directly |
| Hermes | 0.20.4 | executed | executed | executed | executed | works directly |

Ten clients, forty stage results — 34 executed, 6 blocked, 0 not-applicable —
and ten overall statuses: eight works directly, one works through an adapter,
one failed, none unsupported.

Every client was assessed at the same version it carried in the superseded
matrix, so this re-run isolates the package change from any client change.

## What the re-run changed, and what it did not

**No verdict changed, and no stage result changed.** All ten statuses stand
where they stood: eight clients work directly, OpenAI Codex works through an
adapter, Cursor Agent failed. The distribution of the forty stage results is
identical. That is the honest outcome and not a shortcut — every stage was
executed again, and the section below names what was observed rather than
asserting that nothing moved.

**Three recorded digests changed, because the assessed bytes changed.** All
three are consequences of the same regenerated build artifact:

| What | Superseded matrix | This matrix |
|---|---|---|
| Package tree digest, 23 files | `6e6b57c1…8415` | `da46ca77…08c5` |
| Muse content digest, `unifi-network` | `4df21d6c…7139` | `30dd7da8…dcd6` |
| Muse content digest, `unifi-protect` | `9680d149…9484` | `7156c254…9551` |

Muse is the one client that reports a content digest over what it installed, so
it is the one row where a package-byte change is visible in the client's own
output rather than only in this repository's recomputation. Both new values
reproduced identically across two independent installs from two differently
named source directories, which is what makes them an identifier rather than a
one-off.

**One observation is stated more precisely than before, on the same facts.**
The superseded matrix recorded that Claude Code's session-scoped local-plugin
flag resolves the `com.infiquetra.claude/` client extension directory. It does,
and the numbers reproduced exactly — one skill, one agent, about 52 tokens
always-on. What the earlier record left out is that the client identifies that
directory by its own directory name, `com.infiquetra.claude`, not as `unifi`, so
the component inventory has to be asked for under that identifier. That is a
naming detail of the client, not a change in what it resolved, and it is
recorded here so the command in the row below is the command that actually
works.

## The finding that cuts across every row

**The package's skill entrypoints run, on every client that reached the
invocation stage.** Both `unifi_network_client.py --help` and
`unifi_protect_client.py --help` exit 0 and print their argument parser's usage
text — 29 lines and 21 lines respectively — with no controller credential in the
environment, no host argument, and no network call. That is true from the
portable root, from a symbolic link, and from each client-owned installed copy.
Each client resolves its import of the shared backoff primitive through the
regenerated bundle in the `_bundled/` directory beside it, which was confirmed
by reading the resolved module's path back out of the interpreter after import.

Two limits on that claim, recorded rather than glossed:

1. **The entrypoints need their two declared third-party dependencies.** Both
   clients import `requests` and `urllib3` at module scope, which the package
   README states. The invocation stage ran in an interpreter that had both. On a
   runtime without them, `--help` fails at import — for a different reason than
   the one the earlier repair fixed, and one the package documents rather than
   hides.
2. **`--help` is a parser round trip, not a controller round trip.** It proves
   the module graph resolves and the argument parser builds. It proves nothing
   about whether any subcommand talks to a controller correctly, which no
   credential-free assessment can prove.

A third limit belongs to the regenerated bundle specifically, and is recorded
here because this re-run is the reason it is in scope. Fleet Core 0.25.1 imports
`UTC` from `datetime`, which exists only on Python 3.11 and newer, while this
catalog documents a 3.10 floor. Every invocation below ran on an interpreter
above that floor. What this matrix therefore does not show is the 3.10 case; it
is [queued as an open decision](../engineering-journal/QUEUED.md) rather than
answered here.

**Superseding note, added 2026-08-22 after this assessment ran.** The decision
that paragraph defers is now made, and the paragraph is left standing because it
records what was true when the stages ran. The catalog's minimum supported
Python is `python>=3.12`, so the 3.10 case this matrix does not show is no
longer a case the catalog claims to support, and the gap it names is closed by
narrowing the claim rather than by any result below changing. Every stage
result, status, and digest on this page is untouched and still describes the
assessment as it was run. See
[the floor decision](../engineering-journal/DECISIONS.md#the-portable-catalogs-minimum-supported-python-is-python312).

## Per-client detail

### Claude Code — works directly

The client accepted the portable package root through its session-scoped local
plugin flag and resolved the full component inventory: two skills, no agents,
hooks, MCP servers, or LSP servers. Its user-scope marketplace installer refused
the same directory, naming the Claude marketplace file the package does not
carry — a constraint on distribution, not on compatibility. The
`com.infiquetra.claude/` client extension directory is resolved by the same
session flag, under its own directory name, reporting one skill and one agent;
it is refused by the same marketplace installer, for the same missing file.

### OpenAI Codex — works through an adapter

The marketplace is this client's only placement path: it exposes no
local-plugin-directory flag and no skills surface at all. It refused both the
portable root and the client extension directory with the same message, that the
marketplace root holds no supported manifest. A Codex marketplace manifest is the
identified adapter; it was not built here.

### Cursor Agent — failed

Every extension surface refuses without account authentication, so all four
stages are blocked. Two independent obstacles, worth separating: the marketplace
subcommand's own help declares a git repository URL as its only argument, so a
local portable directory could not be added even with credentials; and the
local-plugin-directory flag is a session flag, whose session refuses before it
reports any plugin state. The blocking cause is the client's credential gate,
not the package.

### Qwen — works directly

The strongest single result. The client accepted the portable package root,
read the portable manifest, and reports the package's origin as `AgentPlugins` —
it names the Agent Plugins format as the one it recognized. Both skills resolved
and the extension is enabled at user and workspace scope. What it records under
its own extensions directory is a link pointer, so the path it resolves for
invocation is the portable root itself.

### Grok — works directly

The client validated the portable manifest on its own terms, then installed from
the local directory into a client-owned copy. Installing from a directory
requires an explicit local trust flag, which the client names in its own refusal
message; that flag is an installation trust, not a write confirmation against any
controller. The invocation ran out of the client-owned copy.

### OpenCode — works directly

The client's own built-in configuration skill documents `~/.agents/skills` as an
auto-loaded external skill location — the shared path this pilot expected to be
the working mechanism for loose skills, and it is. There is no install command
for that path, so placement is a copy into it. The client returned each skill's
full parsed body, which is load proven rather than inferred.

### Gemini CLI — works directly

The client resolved each skill's frontmatter, prompted for local consent naming
the link destination, and linked both as symbolic links to the portable
directories, so what it holds is the package's own bytes. Both report enabled
with no diagnostic. Injection into the session system prompt is not observable
without credentials, so what is confirmed is definition load, not session
injection.

### Muse — works directly

The client validates a portable skill directory as-is and installs it with a
content digest and per-file digest inventory. Those content digests are recorded
in the machine-readable record below, which makes this row the one client whose
installed bytes are independently identifiable from public evidence alone, and
the one row where the re-synchronized bundle is visible in a client's own
output. One limitation, recorded rather than worked around: the portable package
root is not an installable unit for this client, which requires a `SKILL.md` at
the root of what it installs, so the two skill directories are installed
individually. No vendor artifact is added either way, which is why this remains
"works directly".

### Agy — works directly

The client validated the portable package root, reporting two skills processed
and every other component absent, then installed from the local path and
re-validated the client-owned installed copy with the same result. Validated
separately, the `com.infiquetra.claude/` client extension directory yielded one
skill, one agent, and one command converted to a skill.

### Hermes — works directly

Both skills were placed at profile scope, list as enabled, and the client's own
offline fresh-session prompt report resolves a skills index containing exactly
those two entries, where before placement it was empty. That report is generated
without credentials and without a live session, which is why it counts as load
rather than as inventory.

## Binding, and what a superseded matrix may claim

A matrix that names a file count and a tree digest looks bound to its artifact.
The first publication of this document proved it is not enough to *look* bound:
it carried a well-formed 64-character digest of a package that had been replaced,
and passed every check, because the validator confirmed the digest's shape and
never recomputed it.

Validation now recomputes the fingerprint of `plugins/unifi/` on every run and
compares all four identifying fields — package name, version, file count, and
tree digest — against the record below. The tree digest is defined so a third
party can reproduce it from the published bytes:

1. Walk the package root and keep every regular file, excluding checkout noise
   (`__pycache__`, compiled bytecode, `.DS_Store`).
2. Sort the surviving paths by their POSIX form, relative to the package root.
3. For each, emit the line `<sha256 of the file's bytes>` + two spaces +
   `<relative path>` + newline.
4. The tree digest is the SHA-256 of those lines concatenated, encoded UTF-8.

The relative path is inside the hashed text on purpose: hashing the file digests
alone would leave a pure rename invisible, and a rename is exactly the drift a
binding exists to catch.

To read the current fingerprint without validating anything:

```console
python3 scripts/check_compatibility_matrix.py --print-fingerprint
```

There is deliberately no flag that writes that fingerprint back into this
document. Refreshing the numbers without re-running the assessment is precisely
the failure this binding exists to catch; a tool that did it in one keystroke
would reintroduce it. This re-run is the demonstration: the binding failed on a
regenerated build artifact, and the way it was cleared was forty stage results,
not one edited digest.

**Retiring a matrix.** A document may exempt itself from the binding by
declaring itself superseded, with three HTML comment directives before its
record:

```
<!-- matrix-status: superseded -->
<!-- superseded-by: <the current matrix's filename> -->
<!-- superseded-reason: <why it no longer describes the package> -->
```

The exemption carries obligations. The named successor must exist and must
itself be current, so a supersession chain ends somewhere real. And a superseded
document whose fingerprint *does* still identify the shipped tree is rejected —
otherwise the live matrix could be marked superseded to switch its own binding
off, which would rebuild the trap this repair removed. `matrix-status` defaults
to `current` when absent, so a document has to say something to be let off the
binding.

Two documents now sit on the superseded side of that rule, and both name this
one as their successor. That is a chain of two, not a chain of one; it ends at a
current matrix, which is what the rule requires.

## The machine-readable record

Everything above is derived from the record below. It validates against
[`schemas/compatibility-matrix.schema.json`](../../schemas/compatibility-matrix.schema.json),
a closed schema, and against the public-evidence rules described at the top of
this document. Run the check with:

```console
python3 scripts/check_compatibility_matrix.py
```

With no argument that validates every matrix document in `docs/evidence/`,
current and superseded alike: retiring a document withdraws its claim about the
current package, not the coverage and redaction rules it was published under.

In recorded commands, `<package>` is the assessed copy of the portable package
root, `<skill>` one portable skill directory inside it, `<client-home>` that
client's isolated home directory, and `<plugin-id>` a client-generated
installation identifier.

```json
{
  "$schema": "../../schemas/compatibility-matrix.schema.json",
  "schema_version": "1",
  "assessed_on": "2026-08-22",
  "package": {
    "name": "unifi",
    "version": "2.0.0",
    "file_count": 23,
    "tree_sha256": "da46ca77d5d5290339586bdae87cbc8cb192f233f4b2f863e623b9e2b57308c5"
  },
  "method": {
    "stages": [
      "placement",
      "discovery",
      "load",
      "invocation"
    ],
    "isolation": "Each client ran against its own empty home directory in a scratch area, so no assessment read or wrote the operator's real client configuration. Every stage result reflects a first-run install rather than an already-configured machine. The package root handed to each client was a scratch copy of the shipped tree, fingerprinted before the run and equal to it at 23 files.",
    "credentials": "No client was authenticated and no controller credential was supplied at any stage. Every UNIFI_ variable was removed from the environment before each invocation. Where a client requires credentials before it will report extension state, that stage is recorded blocked with the requirement named rather than satisfied.",
    "network": "No controller call was made at any stage. The invocation stage runs the package's own entrypoint with its credential-free help action and no host argument, so no request leaves the machine. No mutating operation was invoked and no command passed a write confirmation."
  },
  "clients": [
    {
      "name": "Claude Code",
      "version": "2.1.240",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "claude plugin marketplace add <package>",
          "evidence": "Refused for user-scope installation, naming the marketplace file the portable root does not carry under a .claude-plugin directory. Session-scoped placement succeeded instead by passing the portable root to the client's own local-plugin flag; that flag is re-supplied on each later stage, which is how a session-scoped placement works."
        },
        "discovery": {
          "result": "executed",
          "command": "claude --plugin-dir <package> plugin list --json",
          "evidence": "One plugin entry, identified as unifi from an inline source, scope session, enabled true, with its install path equal to the placed portable root. The client reports the version as unknown because it reads no version from an inline source, not because the manifest lacks one."
        },
        "load": {
          "result": "executed",
          "command": "claude --plugin-dir <package> plugin details unifi",
          "evidence": "Component inventory resolved: skills 2, named unifi-network and unifi-protect; agents 0; hooks 0; MCP servers 0; LSP servers 0; projected always-on cost about 82 tokens, split about 50 for unifi-network and about 30 for unifi-protect. The com.infiquetra.claude client extension directory is resolved by the same session-scoped flag, under its own directory name rather than as unifi, reporting skills 1, agents 1, and about 52 tokens always-on. Its refusal is confined to the marketplace installer, which asks it for the same missing marketplace file."
        },
        "invocation": {
          "result": "executed",
          "command": "python3 <package>/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Credential-free, no host argument, no network call, every UNIFI_ variable removed from the environment. Exit status 0 and the argument parser's usage text on standard output: unifi_network_client.py prints 29 lines naming its twelve resource subcommands, unifi_protect_client.py prints 21 lines naming its six. Both clients resolve their imports through the regenerated bundle in the _bundled directory beside them, confirmed by reading the resolved module path back out of the interpreter after import."
        }
      },
      "status": "works-directly",
      "reason": "Placed, discovered, and loaded the portable package root as shipped with no vendor-specific artifact added, resolving both skills in the client's own component inventory, and ran the package's own entrypoint from the path it resolved. Its user-scope marketplace installer needs a Claude marketplace file the package does not carry, which constrains distribution rather than compatibility."
    },
    {
      "name": "OpenAI Codex",
      "version": "0.149.0",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "codex plugin marketplace add <package>",
          "evidence": "Refused with an invalid-marketplace error stating that the marketplace root contains no supported manifest. The same command against the com.infiquetra.claude client extension directory was refused identically. The client's own command-line help lists no local-plugin-directory flag and no skills surface at all, so the marketplace is its only placement path."
        },
        "discovery": {
          "result": "executed",
          "command": "codex plugin list",
          "evidence": "The inventory reports no marketplace plugins found, consistent with the refused placement. The plugin subcommand's own help lists four operations, all of them marketplace-scoped: add, list, marketplace, and remove."
        },
        "load": {
          "result": "blocked",
          "reason": "Nothing was placed, so the client holds nothing to load, and it offers no local-directory load path that would bypass the marketplace."
        },
        "invocation": {
          "result": "blocked",
          "reason": "The client resolved no path to the package, so there is no client-resolved entrypoint to invoke. The same bytes run credential-free under every client that did resolve a path, but that was not proven through this client and is not claimed here."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "The client has a working plugin mechanism but consumes only marketplace-shaped packages, and its own error names the missing supported manifest. A Codex marketplace manifest is the identified adapter. It was not built here, because building one is remediation and outside this assessment."
    },
    {
      "name": "Cursor Agent",
      "version": "2026.08.11",
      "stages": {
        "placement": {
          "result": "blocked",
          "reason": "Refused with an authentication-required error naming its login command and its two credential environment variables. The marketplace subcommand's own help declares a git repository URL as its only argument, so a local portable directory could not be added even with credentials. The assessment is credential-free by policy, so no placement path was reachable."
        },
        "discovery": {
          "result": "blocked",
          "reason": "The client's only inventory command lists the marketplaces visible to an account, and it refused with an authentication-required error. There is no offline plugin inventory command to fall back to."
        },
        "load": {
          "result": "blocked",
          "reason": "The session-scoped local-plugin flag was supplied with the portable root, both alongside a plugin-state query and alongside a non-interactive session, and the client refused with an authentication-required error before reporting any plugin load state, so load success and load failure are indistinguishable here."
        },
        "invocation": {
          "result": "blocked",
          "reason": "The client resolved no path to the package, so there is no client-resolved entrypoint to invoke."
        }
      },
      "status": "failed",
      "reason": "Assessed on every documented extension surface, and none could be exercised. The blocking cause is the client's credential gate across all four stages, not the package: its marketplace accepts only a git repository URL, and its local-plugin flag requires an authenticated session."
    },
    {
      "name": "Qwen",
      "version": "0.21.15",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "qwen extensions link <package>",
          "evidence": "Accepted the portable package root directly. The client read the portable manifest, reported the package name and version 2.0.0 with its description, listed both skills it would install, prompted for consent, and confirmed the extension linked successfully and enabled."
        },
        "discovery": {
          "result": "executed",
          "command": "qwen extensions list",
          "evidence": "One extension, unifi at version 2.0.0, with its origin reported as the Agent Plugins format and its source type reported as a link, enabled true at both user and workspace scope."
        },
        "load": {
          "result": "executed",
          "command": "qwen extensions list",
          "evidence": "The same inventory resolves the units inside the package: skills unifi-network and unifi-protect, read from the portable manifest. The path the client reports is the portable root itself, because a link records a pointer rather than a copy, which the client's own install record confirms by naming the source and a link type. Session-level injection is not observable credential-free, because a non-interactive run reports that no authentication type is selected before it reports extension state."
        },
        "invocation": {
          "result": "executed",
          "command": "python3 <package>/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Credential-free, no host argument, no network call, every UNIFI_ variable removed from the environment. Exit status 0 and the argument parser's usage text on standard output: unifi_network_client.py prints 29 lines naming its twelve resource subcommands, unifi_protect_client.py prints 21 lines naming its six. Both clients resolve their imports through the regenerated bundle in the _bundled directory beside them."
        }
      },
      "status": "works-directly",
      "reason": "Accepted the portable package root as shipped with no vendor-specific artifact added, named the Agent Plugins format as the origin it recognized, resolved both skills, enabled the extension at user and workspace scope, and ran the entrypoint from the path it reports."
    },
    {
      "name": "Grok",
      "version": "1.0.5",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "grok plugin install <package> --trust",
          "evidence": "A prior validate run reported the plugin manifest valid, with name unifi, version 2.0.0, and components of one skill directory, no command directories, and no agent directories. Installing from a local directory requires an explicit local trust flag, which the client names in its own refusal message; supplied, the client reported one plugin installed. That flag is an installation trust, not a write confirmation against any controller."
        },
        "discovery": {
          "result": "executed",
          "command": "grok plugin list",
          "evidence": "One installed plugin, unifi, under a client-generated installation identifier, recorded against the local source directory it was installed from."
        },
        "load": {
          "result": "executed",
          "command": "grok plugin details unifi",
          "evidence": "Resolved unifi at version 2.0.0 with its description and components of one skill directory, no command directories, and no agent directories, against a client-owned installed copy distinct from the source directory, with its install and update timestamps recorded."
        },
        "invocation": {
          "result": "executed",
          "command": "python3 <client-home>/.grok/installed-plugins/<plugin-id>/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Run from the client-owned installed copy rather than the source directory. Credential-free, no host argument, no network call, every UNIFI_ variable removed from the environment. Exit status 0 and the argument parser's usage text on standard output: unifi_network_client.py prints 29 lines naming its twelve resource subcommands, unifi_protect_client.py prints 21 lines naming its six. The installed copy was fingerprinted after the run at 23 files and the same tree digest as the shipped package."
        }
      },
      "status": "works-directly",
      "reason": "Validated the portable manifest on its own terms, installed the portable package root from a local directory with no vendor-specific artifact added, resolved the package and its skill directory from a client-owned installed copy, and ran the entrypoint out of that copy."
    },
    {
      "name": "OpenCode",
      "version": "1.18.18",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "cp -R <skill> <client-home>/.agents/skills/",
          "evidence": "The client's own built-in configuration skill documents the shared agents skills directory as an auto-loaded external skill location. The client offers no install command for that path, so placement is a copy into it. Both portable skill directories were placed as shipped."
        },
        "discovery": {
          "result": "executed",
          "command": "opencode debug skill",
          "evidence": "Three skills reported in total: the client's own built-in one, plus unifi-network and unifi-protect, each at its placed location."
        },
        "load": {
          "result": "executed",
          "command": "opencode debug skill",
          "evidence": "The same command returns each placed skill's resolved description and full parsed body: unifi-network with 174 description characters and 5682 body characters, unifi-protect with 115 and 3455. The definitions are parsed and held by the client rather than merely listed."
        },
        "invocation": {
          "result": "executed",
          "command": "python3 <client-home>/.agents/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Run from the placed path the client resolved. Credential-free, no host argument, no network call, every UNIFI_ variable removed from the environment. Exit status 0 and the argument parser's usage text on standard output: unifi_network_client.py prints 29 lines naming its twelve resource subcommands, unifi_protect_client.py prints 21 lines naming its six. Both clients resolve their imports through the regenerated bundle in the _bundled directory beside them."
        }
      },
      "status": "works-directly",
      "reason": "Auto-loads the portable skill units as shipped from the shared agents skills directory the client itself documents, with no vendor-specific artifact added, returns each skill's full parsed body, and runs the entrypoint from the placed path."
    },
    {
      "name": "Gemini CLI",
      "version": "0.44.1",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "gemini skills link <skill>",
          "evidence": "Run once per portable skill directory. The client resolved each skill's name and description from its frontmatter, reported three items in the directory, presented a local consent prompt naming the link destination, and reported the skills linked successfully once consent was given. Both landed as symbolic links to the portable directories, so what the client holds is the package's own bytes."
        },
        "discovery": {
          "result": "executed",
          "command": "gemini skills list --all",
          "evidence": "Both skills reported as enabled, with their resolved descriptions and locations, alongside the client's own built-in skill."
        },
        "load": {
          "result": "executed",
          "command": "gemini skills list --all",
          "evidence": "Each skill's frontmatter description was resolved and printed by the client's own loader, and each is reported enabled with no diagnostic. Injection into the session system prompt is not observable without credentials, so what is confirmed here is definition load, not session injection."
        },
        "invocation": {
          "result": "executed",
          "command": "python3 <client-home>/.gemini/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Run through the link the client created. Credential-free, no host argument, no network call, every UNIFI_ variable removed from the environment. Exit status 0 and the argument parser's usage text on standard output: unifi_network_client.py prints 29 lines naming its twelve resource subcommands, unifi_protect_client.py prints 21 lines naming its six. Both clients resolve their imports through the regenerated bundle in the _bundled directory beside them."
        }
      },
      "status": "works-directly",
      "reason": "Linked the portable skill units as shipped with no vendor-specific artifact added, resolved each skill's frontmatter, reports both enabled with no diagnostic, and runs the entrypoint through the link it created."
    },
    {
      "name": "Muse",
      "version": "0.2.1",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "muse skills install <skill> --scope user --json",
          "evidence": "A prior validate run reported the portable skill directory valid, with a per-file digest inventory naming four files for unifi-network and four for unifi-protect, an empty diagnostics array, and a common-subset compatibility profile reported compatible. Installation succeeded for both at user scope, each recorded with a content digest over the installed unit and a local source: unifi-network 30dd7da8760990b0a1d854ae2b4c3cc339c72f6ad517d00a7c97718aade8dcd6, unifi-protect 7156c2545d9fe21487f419f8762c62c53eda19eb7f4299c3bb5d0b34c0b59551. Both values reproduced identically across two independent installs from two differently named source directories. The portable package root itself is refused as an installable unit, with an invalid-skill-package error requiring a SKILL.md at the root of what it installs, so the two skill directories are installed individually; no vendor artifact is added either way."
        },
        "discovery": {
          "result": "executed",
          "command": "muse skills list --source user --json",
          "evidence": "Both skills present at user scope with resolved names and descriptions, activation reported on, an empty diagnostics array for each, and a startup context cost of 262 bytes for unifi-network and 199 for unifi-protect."
        },
        "load": {
          "result": "executed",
          "command": "muse skills inspect unifi-network --json",
          "evidence": "The definition resolved with activation reported on and an empty diagnostics array."
        },
        "invocation": {
          "result": "executed",
          "command": "python3 <client-home>/.config/muse/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Run from the client-owned installed copy. Credential-free, no host argument, no network call, every UNIFI_ variable removed from the environment. Exit status 0 and the argument parser's usage text on standard output: unifi_network_client.py prints 29 lines naming its twelve resource subcommands, unifi_protect_client.py prints 21 lines naming its six. Each installed unit was fingerprinted after the run at four files and the same tree digest as the corresponding source unit."
        }
      },
      "status": "works-directly",
      "reason": "Validated and installed the portable skill units as shipped with no vendor-specific artifact added, reporting activation on, zero diagnostics, and a content digest for each, and runs the entrypoint from the installed copy. The package root is not a unit this client installs, which changes the placement granularity rather than requiring an adapter."
    },
    {
      "name": "Agy",
      "version": "1.1.18",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "agy plugin install <package>",
          "evidence": "A prior validate run reported the portable package root acceptable with two skills processed, and agents, commands, MCP servers, and hooks each skipped as absent. Installation from the local path reported the same two skills processed. Validated separately, the com.infiquetra.claude client extension directory reported one skill, one agent, and one command converted to a skill."
        },
        "discovery": {
          "result": "executed",
          "command": "agy plugin list",
          "evidence": "One import named unifi, with its components reported as skills and its import timestamp recorded."
        },
        "load": {
          "result": "executed",
          "command": "agy plugin validate <client-home>/.gemini/config/plugins/unifi",
          "evidence": "Re-validated against the client-owned installed copy rather than the source directory: acceptable, with two skills processed, and both skill directories present in the installed tree."
        },
        "invocation": {
          "result": "executed",
          "command": "python3 <client-home>/.gemini/config/plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Run from the client-owned installed copy. Credential-free, no host argument, no network call, every UNIFI_ variable removed from the environment. Exit status 0 and the argument parser's usage text on standard output: unifi_network_client.py prints 29 lines naming its twelve resource subcommands, unifi_protect_client.py prints 21 lines naming its six. The installed copy was fingerprinted after the run at 23 files and the same tree digest as the shipped package."
        }
      },
      "status": "works-directly",
      "reason": "Validated and installed the portable package root as shipped with no vendor-specific artifact added, processing both skills, re-validated the client-owned installed copy with the same result, and ran the entrypoint out of that copy."
    },
    {
      "name": "Hermes",
      "version": "0.20.4",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "cp -R <skill> <client-home>/.hermes/skills/",
          "evidence": "Both portable skill directories were copied into the client's own profile-scope skills directory, which is the source the client labels local. This re-run assessed profile scope only, matching the superseded matrix; the project-scope placement the first publication also tried is not re-asserted here."
        },
        "discovery": {
          "result": "executed",
          "command": "hermes skills list --source local",
          "evidence": "Both skills listed with source local, trust local, and status enabled; totals reported as no hub-installed skills, no built-in skills, two local skills, two enabled and none disabled."
        },
        "load": {
          "result": "executed",
          "command": "hermes prompt-size --json",
          "evidence": "The client's own offline fresh-session prompt report resolves a skills index of 236 characters in 238 bytes holding exactly two entries, unifi-network and unifi-protect, with per-entry index lines of 83 and 81 bytes. Before placement the same report showed a zero-byte index with no entries, so the change is attributable to the placement."
        },
        "invocation": {
          "result": "executed",
          "command": "python3 <client-home>/.hermes/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Run from the profile-scope placed path the client resolved. Credential-free, no host argument, no network call, every UNIFI_ variable removed from the environment. Exit status 0 and the argument parser's usage text on standard output: unifi_network_client.py prints 29 lines naming its twelve resource subcommands, unifi_protect_client.py prints 21 lines naming its six. Both clients resolve their imports through the regenerated bundle in the _bundled directory beside them."
        }
      },
      "status": "works-directly",
      "reason": "Placed the portable skill units as shipped with no vendor-specific artifact added, listed both as enabled, confirmed load by the client's own fresh-session prompt report resolving exactly those two entries where it previously held none, and ran the entrypoint from the placed path."
    }
  ]
}
```

## What the operator decides next

Two decisions, and neither is taken here.

1. **The two clients that did not consume the package.** OpenAI Codex needs a
   marketplace manifest to be reachable at all. Cursor Agent could not be
   assessed credential-free, and its marketplace accepts only a git repository
   URL, so a local directory is not a path there under any credentials.
2. **Whether "works directly" is now enough to distribute on.** With the
   entrypoints running, the eight direct verdicts mean the clients place,
   enumerate, hold, and can execute this package. What no credential-free
   assessment can tell the operator is whether the subcommands behave correctly
   against a real controller. That proof belongs to a different exercise.

Both decisions the earlier matrices put first are closed. The missing Fleet Core
bundle was repaired, and the re-synchronization to 0.25.1 that regenerated it
is recorded here rather than left as an open item. What the re-synchronization
did open — the Python floor the corrected upstream module raised — is a
different decision, tracked in
[the engineering journal's queue](../engineering-journal/QUEUED.md) and not
answered by any compatibility result above. That decision was taken later the
same day and is recorded in
[the engineering journal](../engineering-journal/DECISIONS.md#the-portable-catalogs-minimum-supported-python-is-python312);
it moved the catalog's floor to `python>=3.12` and changed nothing on this page.
