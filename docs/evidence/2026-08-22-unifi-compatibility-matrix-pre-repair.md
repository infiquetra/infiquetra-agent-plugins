<!-- matrix-status: superseded -->
<!-- superseded-by: 2026-08-22-unifi-compatibility-matrix.md -->
<!-- superseded-reason: The forty stage results describe the 21-file pre-repair package, whose entrypoints aborted at import. The shipped package is 23 files and both entrypoints exit zero, so every invocation-stage result and the matrix-wide finding below are historical. -->

> **Superseded — historical evidence. Do not read this as the current
> compatibility record.**
>
> This is the ten-client assessment exactly as it was first published on
> 22 August 2026. It is kept because the assessment happened and its record
> should not vanish, not because it still describes the package.
>
> **What superseded it:**
> [`2026-08-22-unifi-compatibility-matrix.md`](2026-08-22-unifi-compatibility-matrix.md),
> the re-run against the repaired package.
>
> **Why:** this record binds itself to a 21-file package with tree digest
> `92ed5032…`, and reports that every client reaching the invocation stage hit
> `ModuleNotFoundError` for `fleet_commons_shim`. Both statements were true of
> the package as first assembled. Neither is true of the package this
> repository now ships: it holds 23 files — the two extra are the generated
> `_bundled/retry_backoff.py` outputs that replaced the dropped shim — and both
> `unifi_network_client.py --help` and `unifi_protect_client.py --help` exit
> zero and print usage. The ten placement, discovery, and load results below
> were not invalidated by that repair; the ten invocation results and the
> cross-cutting finding were.
>
> The check that would have caught this did not exist when this document was
> written: `scripts/check_compatibility_matrix.py` validated that the digest
> was *shaped* like a digest, never that it identified the assessed tree. That
> gap is closed — a current matrix now fails validation when its fingerprint
> does not match `plugins/unifi/`, which is why this document has to declare
> itself superseded to remain in the repository at all.

---

# Ten-client compatibility matrix — portable UniFi package

This repository holds the proposed portable source catalog for Infiquetra Agent
Skills and Agent Plugins. One package in it, `plugins/unifi/`, was assembled as a
derived artifact from an upstream Claude Code plugin. This document records what
happened when that package was put in front of every coding-agent client
installed on the operator's machine, on 22 August 2026.

The point of the exercise is to learn which clients can consume a portable
package and which cannot, before anyone commits to a distribution path. It is a
survey, not a release gate.

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
  supplied at any stage. Where a client demands credentials before it will
  report extension state, that stage is recorded blocked with the requirement
  named, not satisfied.
- **Network.** No controller call was made at any stage. The invocation stage
  runs the package's own entrypoint with its credential-free help action and no
  host argument, so no request leaves the machine. No mutating operation was
  invoked and no command passed `--confirm`.

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

Ten clients, forty stage results — 34 executed, 6 blocked, 0 not applicable —
and ten overall statuses: eight works directly, one works through an adapter,
one failed, none unsupported.

## The finding that cuts across every row

**The package's skill scripts do not run, on any client.** Every client that
reached the invocation stage produced the identical failure: the entrypoint
aborts during module import with `ModuleNotFoundError` for `fleet_commons_shim`,
before any argument is parsed. Both `unifi_network_client.py` and
`unifi_protect_client.py` fail this way.

The cause is package-side, not client-side. The synchronization step deliberately
dropped both copies of `fleet_commons_shim.py`, on the understanding that the
build-time bundle would replace them, but the assembled package contains no
generated bundle and both scripts still import the dropped module at the top of
the file. The package as assembled therefore has no working entrypoint.

Two consequences follow, and they should not be blurred together:

1. Because the failure is identical everywhere, it does not distinguish one
   client from another. The eight "works directly" verdicts describe what the
   clients did with the package — placed it, enumerated it, parsed and held its
   skill definitions — and remain accurate.
2. **No client can actually use this package until that defect is fixed.** Read
   "works directly" as "this client is compatible", never as "this is ready to
   use".

Repairing it is outside this assessment. It is recorded here so the operator can
decide.

## Per-client detail

### Claude Code — works directly

The client accepted the portable package root through its session-scoped local
plugin flag and resolved the full component inventory: two skills, no agents,
hooks, MCP servers, or LSP servers. Its user-scope marketplace installer refused
the same directory, naming the Claude marketplace file the package does not
carry — a constraint on distribution, not on compatibility. Worth noting
separately: the `com.infiquetra.claude/` client extension directory was offered
to the same flag and was *not* recognized, because it carries its manifest at its
own root rather than in the location this client requires.

### OpenAI Codex — works through an adapter

The marketplace is this client's only placement path: it exposes no
local-plugin-directory flag and no skills surface at all. It refused both the
portable root and the client extension directory with the same message, that the
marketplace root holds no supported manifest. A Codex marketplace manifest is the
identified adapter; it was not built here.

### Cursor Agent — failed

Every extension surface refuses without account authentication, so all four
stages are blocked. Two independent obstacles, worth separating: the marketplace
accepts only a git repository URL, so a local portable directory could not be
added even with credentials; and the local-plugin-directory flag is a session
flag, whose session refuses before it reports any plugin state. The blocking
cause is the client's credential gate, not the package.

### Qwen — works directly

The strongest single result. The client accepted the portable package root,
read the portable manifest, and reports the package's origin as `AgentPlugins` —
it names the Agent Plugins format as the one it recognized. Both skills resolved
and the extension is enabled at user and workspace scope.

### Grok — works directly

The client validated the portable manifest on its own terms, then installed from
the local directory into a client-owned copy. Installing from a directory
requires an explicit local trust flag, which the client names in its own refusal
message; that flag is an installation trust, not a write confirmation against any
controller.

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
content digest and per-file digest inventory. One limitation, recorded rather
than worked around: the portable package root is not an installable unit for this
client, which requires a `SKILL.md` at the root of what it installs, so the two
skill directories are installed individually. No vendor artifact is added either
way, which is why this remains "works directly".

### Agy — works directly

The client validated the portable package root, reporting two skills processed
and every other component absent, then installed from the local path and
re-validated the client-owned installed copy with the same result. Validated
separately, the `com.infiquetra.claude/` client extension directory yielded one
skill, one agent, and one command converted to a skill.

### Hermes — works directly

Two placements were tried. At profile scope the result is unambiguous: both
skills list as enabled, and the client's own offline fresh-session prompt report
resolves a skills index containing exactly those two entries, where before
placement it was empty. At project scope — skills placed in a repository's
`.agents/skills/` and the repository trusted — the trust command counted two
project skills, but they did not appear in that same prompt report. Profile-scope
load is confirmed; project-scope load is not, and that discrepancy is the
client's, not the package's.

## The machine-readable record

Everything above is derived from the record below. It validates against
[`schemas/compatibility-matrix.schema.json`](../../schemas/compatibility-matrix.schema.json),
a closed schema, and against the public-evidence rules described at the top of
this document. Run the check with:

```console
python3 scripts/check_compatibility_matrix.py
```

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
    "file_count": 21,
    "tree_sha256": "92ed503207ca6eabfc5a70a892d682ee0030ad0d16db2db436abfb83f7fa240b"
  },
  "method": {
    "stages": ["placement", "discovery", "load", "invocation"],
    "isolation": "Each client ran against its own empty home directory in a scratch area, so no assessment read or wrote the operator's real client configuration. Every stage result reflects a first-run install rather than an already-configured machine.",
    "credentials": "No client was authenticated and no controller credential was supplied at any stage. Where a client requires credentials before it will report extension state, that stage is recorded blocked with the requirement named rather than satisfied.",
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
          "evidence": "Refused for user-scope installation: the client requires a marketplace file under a .claude-plugin directory, which neither the portable root nor the com.infiquetra.claude client extension directory carries. Session-scoped placement succeeded instead by passing the portable root to the client's own local-plugin flag; that flag is re-supplied on each later stage, which is how a session-scoped placement works."
        },
        "discovery": {
          "result": "executed",
          "command": "claude --plugin-dir <package> plugin list --json",
          "evidence": "One plugin entry, identified as unifi from an inline source, scope session, enabled true, with its install path equal to the placed portable root."
        },
        "load": {
          "result": "executed",
          "command": "claude --plugin-dir <package> plugin details unifi",
          "evidence": "Component inventory resolved: skills 2, named unifi-network and unifi-protect; agents 0; hooks 0; MCP servers 0; LSP servers 0; projected always-on cost about 82 tokens. Passed separately, the com.infiquetra.claude client extension directory was not recognized as a plugin, because it carries its manifest at its own root rather than in the location this client requires."
        },
        "invocation": {
          "result": "executed",
          "command": "python3 <package>/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Credential-free, no host argument, no network call. The entrypoint aborts during module import with ModuleNotFoundError for fleet_commons_shim before parsing any argument; unifi_protect_client.py fails identically. This is the package-side defect recorded matrix-wide, identical for every client that reached this stage."
        }
      },
      "status": "works-directly",
      "reason": "Placed, discovered, and loaded the portable package root as shipped with no vendor-specific artifact added, resolving both skills in the client's own component inventory. Its user-scope marketplace installer needs a Claude marketplace file the package does not carry, which constrains distribution rather than compatibility."
    },
    {
      "name": "OpenAI Codex",
      "version": "0.149.0",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "codex plugin marketplace add <package>",
          "evidence": "Refused with an invalid-marketplace error stating that the marketplace root contains no supported manifest. The same command against the com.infiquetra.claude client extension directory was refused identically. The client exposes no local-plugin-directory flag and no skills surface in its command-line help, so the marketplace is its only placement path."
        },
        "discovery": {
          "result": "executed",
          "command": "codex plugin list",
          "evidence": "The inventory reports no marketplace plugins found, consistent with the refused placement."
        },
        "load": {
          "result": "blocked",
          "command": "codex plugin list",
          "reason": "Nothing was placed, so the client holds nothing to load, and it offers no local-directory load path that would bypass the marketplace."
        },
        "invocation": {
          "result": "blocked",
          "reason": "The client resolved no path to the package, so there is no client-resolved entrypoint to invoke. The package-side import failure recorded for every client that reached this stage applies to these bytes too, but was not reached through this client."
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
          "command": "cursor-agent plugin marketplace add <package>",
          "reason": "Refused with an authentication-required error. The marketplace also accepts only a git repository URL, so a local portable directory could not be added even with credentials. The assessment is credential-free by policy, so no placement path was reachable."
        },
        "discovery": {
          "result": "blocked",
          "command": "cursor-agent plugin marketplace list",
          "reason": "Refused with an authentication-required error. The client has no offline plugin inventory command."
        },
        "load": {
          "result": "blocked",
          "command": "cursor-agent --plugin-dir <package> -p <prompt> --output-format text",
          "reason": "The session-scoped local-plugin flag was supplied with the portable root and the client refused with an authentication-required error before reporting any plugin load state, so load success and load failure are indistinguishable here."
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
          "evidence": "Accepted the portable package root directly. The client read the portable manifest, reported the package name and version 2.0.0 with its description, listed both skills it would install, and confirmed the extension linked successfully and enabled."
        },
        "discovery": {
          "result": "executed",
          "command": "qwen extensions list",
          "evidence": "One extension, unifi at version 2.0.0, with its origin reported as the Agent Plugins format, enabled true at both user and workspace scope."
        },
        "load": {
          "result": "executed",
          "command": "qwen extensions list",
          "evidence": "The same inventory resolves the units inside the package: skills unifi-network and unifi-protect, read from the portable manifest. Session-level injection is not observable credential-free, because a non-interactive run reports that no authentication type is selected before it reports extension state."
        },
        "invocation": {
          "result": "executed",
          "command": "python3 <package>/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Run against the linked package, which is the path this client resolved. Credential-free, no host argument, no network call. Aborts during module import with ModuleNotFoundError for fleet_commons_shim, the package-side defect recorded matrix-wide."
        }
      },
      "status": "works-directly",
      "reason": "Accepted the portable package root as shipped with no vendor-specific artifact added, named the Agent Plugins format as the origin it recognized, resolved both skills, and enabled the extension at user and workspace scope."
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
          "evidence": "One installed plugin, unifi, recorded against the local source directory it was installed from."
        },
        "load": {
          "result": "executed",
          "command": "grok plugin details unifi",
          "evidence": "Resolved unifi at version 2.0.0 with its description and components of one skill directory, no command directories, and no agent directories, against a client-owned installed copy distinct from the source directory."
        },
        "invocation": {
          "result": "executed",
          "command": "python3 <client-home>/.grok/installed-plugins/<plugin-id>/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Run from the client-owned installed copy. Credential-free, no host argument, no network call. Aborts during module import with ModuleNotFoundError for fleet_commons_shim, the package-side defect recorded matrix-wide."
        }
      },
      "status": "works-directly",
      "reason": "Validated the portable manifest on its own terms, installed the portable package root from a local directory with no vendor-specific artifact added, and resolved the package and its skill directory from a client-owned installed copy."
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
          "evidence": "Run from the placed path the client resolved. Credential-free, no host argument, no network call. Aborts during module import with ModuleNotFoundError for fleet_commons_shim, the package-side defect recorded matrix-wide."
        }
      },
      "status": "works-directly",
      "reason": "Auto-loads the portable skill units as shipped from the shared agents skills directory the client itself documents, with no vendor-specific artifact added, and returns each skill's full parsed body."
    },
    {
      "name": "Gemini CLI",
      "version": "0.44.1",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "gemini skills link <skill>",
          "evidence": "Run once per portable skill directory. The client resolved each skill's name and description from its frontmatter, presented a local consent prompt naming the link destination, and reported the skills linked successfully once consent was given. Both landed as symbolic links to the portable directories, so what the client holds is the package's own bytes."
        },
        "discovery": {
          "result": "executed",
          "command": "gemini skills list --all",
          "evidence": "Both skills reported as enabled, with their resolved descriptions and locations, alongside the client's own built-in skill."
        },
        "load": {
          "result": "executed",
          "command": "gemini skills list --all",
          "evidence": "Each skill's frontmatter description was resolved and printed by the client's own loader, and each is reported enabled with no diagnostic. Injection into the session system prompt is not observable credential-free, so what is confirmed here is definition load, not session injection."
        },
        "invocation": {
          "result": "executed",
          "command": "python3 <client-home>/.gemini/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Run through the link the client created. Credential-free, no host argument, no network call. Aborts during module import with ModuleNotFoundError for fleet_commons_shim, the package-side defect recorded matrix-wide."
        }
      },
      "status": "works-directly",
      "reason": "Linked the portable skill units as shipped with no vendor-specific artifact added, resolved each skill's frontmatter, and reports both enabled with no diagnostic."
    },
    {
      "name": "Muse",
      "version": "0.2.1",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "muse skills install <skill> --scope user",
          "evidence": "A prior validate run reported the portable skill directory valid, with a per-file digest inventory. Installation succeeded for both skills at user scope, each recorded with a content digest and a local source. The portable package root itself is not an installable unit for this client, which requires a SKILL.md at the root of what it installs, so the two portable skill directories are installed individually; no vendor artifact is added either way."
        },
        "discovery": {
          "result": "executed",
          "command": "muse skills list --source user --json",
          "evidence": "Both skills present at user scope with resolved names and descriptions, activation reported on, and an empty diagnostics array for each."
        },
        "load": {
          "result": "executed",
          "command": "muse skills inspect unifi-network --json",
          "evidence": "The definition resolved with activation reported on and an empty diagnostics array."
        },
        "invocation": {
          "result": "executed",
          "command": "python3 <client-home>/.config/muse/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Run from the client-owned installed copy. Credential-free, no host argument, no network call. Aborts during module import with ModuleNotFoundError for fleet_commons_shim, the package-side defect recorded matrix-wide."
        }
      },
      "status": "works-directly",
      "reason": "Validated and installed the portable skill units as shipped with no vendor-specific artifact added, reporting activation on and zero diagnostics for each. The package root is not a unit this client installs, which changes the placement granularity rather than requiring an adapter."
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
          "evidence": "One import named unifi, with its components reported as skills."
        },
        "load": {
          "result": "executed",
          "command": "agy plugin validate <client-home>/.gemini/config/plugins/unifi",
          "evidence": "Re-validated against the client-owned installed copy rather than the source directory: acceptable, with two skills processed, and both skill directories present in the installed tree."
        },
        "invocation": {
          "result": "executed",
          "command": "python3 <client-home>/.gemini/config/plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Run from the client-owned installed copy. Credential-free, no host argument, no network call. Aborts during module import with ModuleNotFoundError for fleet_commons_shim, the package-side defect recorded matrix-wide."
        }
      },
      "status": "works-directly",
      "reason": "Validated and installed the portable package root as shipped with no vendor-specific artifact added, processing both skills, and re-validated the client-owned installed copy with the same result."
    },
    {
      "name": "Hermes",
      "version": "0.20.4",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "cp -R <skill> <client-home>/.hermes/skills/",
          "evidence": "Two placements were tried. At project scope, both portable skill directories were copied into a repository's agents skills directory and the repository was trusted with the client's own trust command, which reported that two project skills would load in sessions started inside that repository. At profile scope, both were copied into the client's own skills directory, which is the source the client labels local."
        },
        "discovery": {
          "result": "executed",
          "command": "hermes skills list --source local",
          "evidence": "Both skills listed with source local, trust local, and status enabled; totals reported as no hub-installed skills, no built-in skills, two local skills, two enabled and none disabled."
        },
        "load": {
          "result": "executed",
          "command": "hermes prompt-size --json",
          "evidence": "The client's own offline fresh-session prompt report resolves a skills index of 238 bytes holding exactly two entries, unifi-network and unifi-protect. Before placement the same report showed a zero-byte index with no entries, so the change is attributable to the placement. Recorded separately: the project-scope placement's two skills did not appear in this report, so project-scope load is unconfirmed while profile-scope load is confirmed."
        },
        "invocation": {
          "result": "executed",
          "command": "python3 <client-home>/.hermes/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Run from the profile-scope placed path the client resolved. Credential-free, no host argument, no network call. Aborts during module import with ModuleNotFoundError for fleet_commons_shim, the package-side defect recorded matrix-wide."
        }
      },
      "status": "works-directly",
      "reason": "Placed the portable skill units as shipped with no vendor-specific artifact added, listed both as enabled, and confirmed load by the client's own fresh-session prompt report resolving exactly those two entries where it previously held none. The project-scope discrepancy is a client behaviour, recorded but not repaired."
    }
  ]
}
```

## What the operator decides next

Two decisions, and neither is taken here.

1. **The package entrypoint.** No client can run these scripts until the missing
   Fleet Core bundle is resolved. This blocks real use everywhere and is
   independent of any client.
2. **The two clients that did not consume the package.** OpenAI Codex needs a
   marketplace manifest to be reachable at all. Cursor Agent could not be
   assessed credential-free, and its marketplace accepts only a git repository
   URL, so a local directory is not a path there under any credentials.
