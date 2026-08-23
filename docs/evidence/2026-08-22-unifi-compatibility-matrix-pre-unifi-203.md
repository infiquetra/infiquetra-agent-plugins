<!-- matrix-status: superseded -->
<!-- superseded-by: 2026-08-22-unifi-compatibility-matrix.md -->
<!-- superseded-reason: The forty stage results describe portable package 2.0.2 at tree digest 4c256bb2..., before unifi 2.0.3 repaired the credential-value rule a fifth review cycle found defective in both directions: a placeholder standing between an auth scheme word and a credential ended the search, so a real token behind it was cleared, and ordinary operational prose whose first token is a long English word was rejected as a credential. The shipped package is 2.0.3 and fingerprints to 34915c40..., so this record no longer identifies the tree it claims to describe. Its client results and its Cursor correction stand and are carried forward unchanged. -->

# Ten-client compatibility matrix — portable UniFi package

This repository holds the proposed portable source catalog for Infiquetra Agent
Skills and Agent Plugins. One package in it, `plugins/unifi/`, was assembled as a
derived artifact from an upstream Claude Code plugin. This document records what
happened when that package was put in front of every coding-agent client
installed on the operator's machine, on 22 August 2026.

The point of the exercise is to learn which clients can consume a portable
package and which cannot, before anyone commits to a distribution path. It is a
survey, not a release gate.

## This is the fourth re-run, and what it replaces

Four earlier publications of this matrix are preserved as history, each retired
for a different reason:

1. [`2026-08-22-unifi-compatibility-matrix-pre-repair.md`](2026-08-22-unifi-compatibility-matrix-pre-repair.md)
   assessed the package as originally assembled: 21 files, with both skill
   entrypoints aborting at import because the synchronization step had dropped
   `fleet_commons_shim.py` and no generated bundle had yet replaced it.
2. [`2026-08-22-unifi-compatibility-matrix-pre-resync.md`](2026-08-22-unifi-compatibility-matrix-pre-resync.md)
   assessed the repaired 23-file package, at tree digest `6e6b57c1…`, whose
   entrypoints run.
3. [`2026-08-22-unifi-compatibility-matrix-pre-unifi-201.md`](2026-08-22-unifi-compatibility-matrix-pre-unifi-201.md)
   assessed portable package `2.0.0` at tree digest `da46ca77…`, after the
   portable Fleet Core slice was re-synchronized to release 0.25.1 but before the
   UniFi clients themselves were repaired.
4. [`2026-08-22-unifi-compatibility-matrix-pre-unifi-202.md`](2026-08-22-unifi-compatibility-matrix-pre-unifi-202.md)
   assessed portable package `2.0.1` at tree digest `cafe8836…`, after the caller
   half of the `Retry-After` defect was repaired but before the two defects a
   fourth review cycle found.

This document is the re-run against the package as it now ships. What moved since
the last publication is three repairs, all authored at the boundary that owns
them:

- **Fleet Core `0.25.2`** — `parse_retry_after` refuses a non-finite value.
  `float()` accepts `inf`, `-inf`, `nan`, and overlarge literals such as `1e400`,
  so a header carrying one parsed to a non-finite "delay" and travelled on as
  though the server had given a usable hint. The sleep path hid it; the damage
  landed after retries were exhausted, where the caller reduces the hint to whole
  seconds and `math.ceil` raised, costing the operator the typed 429 surface and
  giving them a generic error instead of a wait time.
- **UniFi `2.0.2`** — the Claude-path site-profile loader was pinned to schema
  `1.0` while the portable half of this same package advanced its contract to
  `1.1`. One package disagreed with itself: an operator authoring the `1.1`
  document the package documents had it rejected by their own integration, and a
  credential pasted into a free-text value was refused on one path and accepted on
  the other.
- **Portable, target-owned** — the credential-value rule graded the auth scheme
  word rather than the credential behind it, so `authorization: Bearer <token>`
  passed; `Basic` and `Token` fell under the length floor and were never examined
  at all.

## What this document is, and is not

It is a record of what ten clients did with one package on one machine on one
day. It is not a claim about those clients in general, not a claim that any
client will keep behaving this way, and not a release gate: nothing here decides
whether the package ships.

## How every client was assessed

The same four stages were run against every client, in the same order:

| Stage | What it asks |
|---|---|
| Placement | Can the package, or its portable skill units, be installed or placed where this client documents that it looks? |
| Discovery | Does the client's own inventory command enumerate what was placed? |
| Load | Does the client parse the placed definitions and hold them — resolved metadata, active state, no diagnostic — rather than merely list them? |
| Invocation | Does the safest meaningful credential-free, read-only entrypoint run, from the path this client resolved? |

Held identical across all ten:

- **Isolation.** Nine clients ran against their own empty home directory in a
  scratch area. No assessment read or wrote the operator's real client
  configuration, and every one of those results reflects a first-run install.
  Cursor Agent is the single exception, for a reason the earlier publication of
  this matrix got wrong: that client keeps its authentication in the user's home,
  so an empty scratch home did not test a first-run client, it tested an
  unauthenticated one, and the refusal recorded was the isolation's rather than
  the client's. Cursor was therefore reassessed against the operator's real home
  with the same read-only, credential-free rules as every other row — its
  authentication state recorded only as present, no credential created, changed,
  or read into this evidence, and no account identity published here.
- **Credentials.** No client was authenticated and no controller credential was
  supplied at any stage. Every `UNIFI_` variable was removed from the
  environment before each invocation. Where a client demands credentials before
  it will report extension state, that stage is recorded blocked with the
  requirement named, not satisfied.
- **Network.** No controller call was made at any stage. The invocation stage
  runs the package's own entrypoint with its credential-free help action and no
  host argument, so no request leaves the machine. No mutating operation was
  invoked and no command passed a write confirmation. Where a client required an
  explicit local installation trust before it would install from a directory,
  that trust was given and is named in the row; it authorizes a local install and
  is not a write confirmation against any controller.
- **The interpreter is the declared floor.** Every invocation stage ran on
  `python3.12`, CPython 3.12.13, in a throwaway virtual environment holding only
  the two third-party dependencies the package imports, `requests` and `urllib3`.
  The catalog's declared minimum is `python>=3.12`; running the assessment on a
  newer default interpreter is how a previous floor break reached a green report,
  so the floor is exercised here by explicit path rather than assumed.
- **The assessed copy is the shipped tree.** The package root handed to each
  client was a scratch copy of `plugins/unifi/`, fingerprinted before the run at
  23 files, `4c256bb2…`, equal to the source tree, and recomputed after the run
  and still equal — so no client mutated what was assessed.

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

Nine of ten clients consumed the portable package or its skill units directly.

| Client | Version | Placement | Discovery | Load | Invocation | Status |
|---|---|---|---|---|---|---|
| Claude Code | 2.1.240 | executed | executed | executed | executed | works directly |
| OpenAI Codex | 0.149.0 | executed | executed | blocked | blocked | works through an adapter |
| Cursor Agent | 2026.08.11 | executed | executed | executed | executed | works directly |
| Qwen | 0.21.15 | executed | executed | executed | executed | works directly |
| Grok | 1.0.5 | executed | executed | executed | executed | works directly |
| OpenCode | 1.18.18 | executed | executed | executed | executed | works directly |
| Gemini CLI | 0.44.1 | executed | executed | executed | executed | works directly |
| Muse | 0.2.1 | executed | executed | executed | executed | works directly |
| Agy | 1.1.18 | executed | executed | executed | executed | works directly |
| Hermes | 0.20.4 | executed | executed | executed | executed | works directly |

Ten clients, forty stage results — 38 executed, 2 blocked, 0 not-applicable —
and ten overall statuses: nine works directly, one works through an adapter,
none failed, none unsupported.

Every client was assessed at the same version it carried in the superseded
matrix, so this re-run isolates the package change from any client change.

## What the re-run changed, and what it did not

One status moved, and not because the package changed. Cursor Agent moves from
failed to works directly, because the superseded run had measured an
unauthenticated client rather than the installed one; the correction is described
in that client's row below. Every other status is unchanged: the same eight
clients work directly, and Codex still identifies an adapter it does not have.
That is the expected result for the package itself, because the three repairs
since the last publication changed behaviour inside the package, not the shape a
client sees.

Two observations are new, and both are recorded because they were observed rather
than because they were expected:

- **Qwen no longer records a link pointer.** The superseded matrix recorded
  Qwen's extensions directory as a link back to the portable root. On this run it
  holds a client-owned copy of the package plus one file of its own,
  `.qwen-extension-install.json` — 24 files where the package ships 23. The
  status is unchanged and no vendor artifact was added to the package, but the
  path the client resolves for invocation is now its own copy rather than the
  source tree, and the row below says so.
- **A repair is visible in a client's own output.** Muse records a content digest
  and a per-file digest inventory for what it installs. Its record names
  `scripts/_bundled/retry_backoff.py` at `9e1f2f17…`, equal to the regenerated
  bundle in this repository, which is independent confirmation from a client's own
  bookkeeping that Fleet Core `0.25.2` reached the installed bytes.

## Client detail

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

### Cursor Agent — works directly

Against the client as the operator actually has it installed, the session-scoped
local-plugin path works. A bounded read-only session probe, forbidden filesystem,
shell, network, and UniFi tools, enumerated the loaded components and named the
session-loaded copy of this package. Asked to distinguish that copy from the
marketplace-installed plugin of the same name already on the machine, the client
reported plugin `unifi` contributing exactly two components, skill
`unifi-network` and skill `unifi-protect`, carrying no version in session
context — the same behaviour the other session-scoped client shows, which reads
no version from an inline source. The package's entrypoints then ran from the
path that flag resolved.

Its marketplace subcommand declares a git repository URL as its only argument, so
a local directory cannot be added that way. That constrains distribution, not
compatibility, and it is recorded here rather than in a stage result.

**What the superseded publication said, and why it was wrong.** The previous
matrix recorded this client as failed with all four stages blocked on a
credential gate. That run exported an empty scratch home for isolation, which
stripped the client's existing authentication; what it measured was an
unauthenticated client, not a first-run one. The command was right and the
environment was wrong, and the finding it produced — a client failure — was an
artifact of the harness. It is preserved in the superseded document as history.

### Qwen — works directly

The client accepted the portable package root, read the portable manifest, and
reports the package's origin as `AgentPlugins` — it names the Agent Plugins
format as the one it recognized. It reads the version from the portable manifest
as `2.0.2`, resolves both skills, and reports the extension enabled at user and
workspace scope. Installing from a directory required confirming an installation
trust, which the client prompts for by name; that trust authorizes a local
install and is not a write confirmation against any controller.

What it records under its own extensions directory is a client-owned copy of the
package, not the link pointer the superseded matrix observed, plus one file of
its own bookkeeping. The path it resolves for invocation is therefore its copy.

### Grok — works directly

The client validated the portable manifest on its own terms, reporting name,
version `2.0.2`, and one skill directory, then installed from the local directory
into a client-owned copy. Installing from a directory requires an explicit local
trust flag, which the client names in its own refusal message; that flag is an
installation trust, not a write confirmation against any controller. The
invocation ran out of the client-owned copy.

### OpenCode — works directly

The client's own built-in configuration skill documents `~/.agents/skills` as an
auto-loaded external skill location — the shared path this pilot expected to be
the working mechanism for loose skills, and it is. There is no install command
for that path, so placement is a copy into it. The client returned each skill's
full parsed body, which is load proven rather than inferred, and it did so
without credentials.

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
those two entries, where before placement it was empty — 236 characters where
the baseline was 0. That report is generated without credentials and without a
live session, which is why it counts as load rather than as inventory.

## Binding, and what a superseded matrix may claim

A matrix that names a file count and a tree digest looks bound to its artifact.
The first publication of this document proved it is not enough to *look* bound:
a digest that is merely well formed identifies nothing. `scripts/check_compatibility_matrix.py`
recomputes the digest from the shipped tree and fails when the record and the
tree disagree, so this document cannot survive a change to the package it
describes. That is what makes the fingerprint below a binding rather than a
decoration, and it is why editing the package invalidates this document until it
is re-run.

A superseded matrix keeps its own fingerprint and its own claims. It is history,
not a second current answer, and the `matrix-status` directive at the top of each
file is what distinguishes the two.

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
    "version": "2.0.2",
    "file_count": 23,
    "tree_sha256": "4c256bb20bd054c498056282eb7cbb3cee9c224c422bf1f20bb66422d1d15cfa"
  },
  "method": {
    "stages": [
      "placement",
      "discovery",
      "load",
      "invocation"
    ],
    "isolation": "Each client ran against its own empty home directory in a scratch area, so no assessment read or wrote the operator's real client configuration. Every stage result reflects a first-run install rather than an already-configured machine. The package root handed to each client was a scratch copy of the shipped tree, fingerprinted before the run and equal to it at 23 files, and recomputed after the run and still equal. Every invocation stage ran on python3.12, CPython 3.12.13, which is the catalog's declared minimum interpreter, in a throwaway virtual environment holding only the two third-party dependencies the package imports, requests and urllib3. Running the assessment on a newer default interpreter is how a previous floor break reached a green report, so the floor is exercised by explicit path rather than assumed.",
    "credentials": "No client was authenticated and no controller credential was supplied at any stage. Every UNIFI_ variable was removed from the environment before each invocation. Where a client requires credentials before it will report extension state, that stage is recorded blocked with the requirement named rather than satisfied.",
    "network": "No controller call was made at any stage. The invocation stage runs the package's own entrypoint with its credential-free help action and no host argument, so no request leaves the machine. No mutating operation was invoked and no command passed a write confirmation. Where a client required an explicit local installation trust before installing from a directory, that trust was given and is named in the client's row; it authorizes a local install and is not a write confirmation against any controller."
  },
  "clients": [
    {
      "name": "Claude Code",
      "version": "2.1.240",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "claude --plugin-dir <package> plugin list",
          "evidence": "Refused for user-scope installation, naming the marketplace file the portable root does not carry under a .claude-plugin directory. Session-scoped placement succeeded instead by passing the portable root to the client's own local-plugin flag; that flag is re-supplied on each later stage, which is how a session-scoped placement works."
        },
        "discovery": {
          "result": "executed",
          "command": "claude --plugin-dir <package> plugin list",
          "evidence": "One session-only plugin entry, identified as unifi from an inline source, status loaded, with its path equal to the placed portable root. The client reports the version as unknown because it reads no version from an inline source, not because the manifest lacks one."
        },
        "load": {
          "result": "executed",
          "command": "claude --plugin-dir <package> plugin details unifi",
          "evidence": "Component inventory resolved: skills 2, named unifi-network and unifi-protect; agents 0; hooks 0; MCP servers 0; LSP servers 0; projected always-on cost about 82 tokens, split about 50 for unifi-network and about 30 for unifi-protect. The com.infiquetra.claude client extension directory is resolved by the same session-scoped flag, under its own directory name rather than as unifi, reporting skills 1 and agents 1. Its refusal is confined to the marketplace installer, which asks it for the same missing marketplace file."
        },
        "invocation": {
          "result": "executed",
          "command": "python3.12 <package>/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Credential-free, no host argument, no network call, every UNIFI_ variable removed from the environment, on CPython 3.12.13 which is the catalog's declared minimum interpreter. Exit status 0 and the argument parser's usage text on standard output for both entrypoints. Both clients resolve their imports through the regenerated bundle in the _bundled directory beside them, confirmed by reading the resolved module path back out of the interpreter after import; parse_retry_after('1e400') returns None there, which is the Fleet Core 0.25.2 repair present in the bytes a client actually loads."
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
          "evidence": "Refused with 'marketplace root does not contain a supported manifest', for the portable package root and for the com.infiquetra.claude client extension directory alike. The attempt ran and returned a specific, actionable refusal, which is what makes this stage executed rather than blocked."
        },
        "discovery": {
          "result": "executed",
          "command": "codex plugin list",
          "evidence": "'No marketplace plugins found.' The marketplace is this client's only placement path: it exposes no local-plugin-directory flag, and its top-level help names no skills surface at all."
        },
        "load": {
          "result": "blocked",
          "reason": "Nothing was placed, so there is nothing to load. Blocked on the absent adapter rather than on any package defect."
        },
        "invocation": {
          "result": "blocked",
          "reason": "No client-resolved path exists, because placement produced none. The package's entrypoints run on this machine, but not from a path this client resolved, and a stage that did not run through the client is recorded blocked rather than borrowed from another client's result."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "The client cannot consume the portable form as shipped and its own tooling names the missing artifact: a Codex marketplace manifest. That adapter identifies the path; it was not built here, because building it is remediation and out of scope for a survey."
    },
    {
      "name": "Cursor Agent",
      "version": "2026.08.11",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "cursor-agent --plugin-dir <package> --mode ask --trust -p --output-format text \"Report the locally loaded plugin and component names available from session context. Do not use filesystem, shell, network, or UniFi tools.\"",
          "evidence": "Placed through the client's session-scoped local-plugin flag against an authenticated client. Authentication state was confirmed present and is recorded only as present; no credential was created, changed, or read into this evidence. The flag is re-supplied on each later stage, which is how a session-scoped placement works. Its marketplace subcommand separately declares a git repository URL as its only argument, so a local directory cannot be added that way; that is a distribution limitation and not a compatibility result."
        },
        "discovery": {
          "result": "executed",
          "command": "cursor-agent --plugin-dir <package> --mode ask --trust -p --output-format text \"Report the locally loaded plugin and component names available from session context. Do not use filesystem, shell, network, or UniFi tools.\"",
          "evidence": "The session enumerated its loaded plugin-backed components and listed the session-loaded copy of this package alongside the client's own marketplace-installed plugins, naming unifi-network and unifi-protect. The probe was bounded to session context and explicitly forbidden filesystem, shell, network, and UniFi tools, so it reports what the client loaded rather than what is on disk."
        },
        "load": {
          "result": "executed",
          "command": "cursor-agent --plugin-dir <package> --mode ask --trust -p --output-format text \"From session context only, for the plugin loaded from the session-scoped local plugin directory (not any marketplace-installed plugin of the same name): report its plugin name, its version if session context carries one, and the exact component names it contributes. Do not use filesystem, shell, network, or UniFi tools.\"",
          "evidence": "Asked to distinguish the session-loaded directory from any marketplace-installed plugin of the same name, the client reported plugin unifi contributing exactly two components, skill unifi-network and skill unifi-protect, and reported no version in session context. That resolves component identity rather than a directory listing, which is what separates load from discovery. The absent version matches the behaviour of the other session-scoped client, which likewise reads no version from an inline source."
        },
        "invocation": {
          "result": "executed",
          "command": "python3.12 <package>/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Exit status 0 and usage text for both entrypoints, credential-free and with no host argument, on CPython 3.12.13, from the package path the session-scoped flag resolved — the same client-resolved-path rule applied to every other row."
        }
      },
      "status": "works-directly",
      "reason": "Against the client as the operator actually has it installed, the session-scoped local-plugin path placed, discovered, and loaded the portable package as shipped, resolving both skills by name with no vendor-specific artifact added, and the package's entrypoints ran from the path the client resolved. Its marketplace accepts only a git repository URL, which constrains distribution rather than compatibility. A superseded publication of this matrix recorded this client as failed; that run had exported an empty scratch HOME, which stripped the client's existing authentication and measured an unauthenticated first-run client rather than the installed one. The isolation rule is retained for every other client and is relaxed here only because it was the isolation, not the client, that produced the earlier refusal."
    },
    {
      "name": "Qwen",
      "version": "0.21.15",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "qwen extensions install <package>",
          "evidence": "Installed and enabled after confirming the installation trust the client prompts for by name, having first printed the two skills it was about to install. That trust authorizes a local install and is not a write confirmation against any controller."
        },
        "discovery": {
          "result": "executed",
          "command": "qwen extensions list",
          "evidence": "One entry, unifi 2.0.2, marked with a success indicator, reporting Origin AgentPlugins — the client names the Agent Plugins format as the one it recognized — with Enabled (User) true and Enabled (Workspace) true, and the description read from the portable manifest."
        },
        "load": {
          "result": "executed",
          "command": "qwen extensions list",
          "evidence": "The same command resolves both skills by name, unifi-network and unifi-protect, alongside the version and enabled state, so the definitions are held rather than merely enumerated. No diagnostic was raised."
        },
        "invocation": {
          "result": "executed",
          "command": "python3.12 <client-home>/.qwen/extensions/unifi/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Exit status 0 and usage text for both entrypoints, credential-free and with no host argument, on CPython 3.12.13. The path is the client's own copy: unlike the superseded matrix, which recorded a link pointer back to the portable root, this run's extensions directory holds a copy of the package plus one file of the client's own bookkeeping, .qwen-extension-install.json, at 24 files where the package ships 23. No vendor artifact was added to the package itself."
        }
      },
      "status": "works-directly",
      "reason": "Placed, discovered, loaded, and invoked the portable package as shipped, reading the portable manifest and naming the Agent Plugins format by name. The client copies rather than links what it installs, which changes the path invocation resolves but adds nothing to the package."
    },
    {
      "name": "Grok",
      "version": "1.0.5",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "grok plugin install <package> --trust",
          "evidence": "Validated first with 'grok plugin validate <package>', which reported the manifest valid, name unifi, version 2.0.2, and one skill directory with no command or agent directories. Installing from a directory requires an explicit local trust flag, which the client names in its own refusal message; that flag is an installation trust, not a write confirmation against any controller. With it, one plugin installed."
        },
        "discovery": {
          "result": "executed",
          "command": "grok plugin list",
          "evidence": "One entry under a client-generated identifier, <plugin-id>, recorded as local with its source path equal to the placed portable root."
        },
        "load": {
          "result": "executed",
          "command": "grok plugin details <plugin-id>",
          "evidence": "Resolved plugins 1, named unifi at version 2.0.2 read from the portable manifest, with the description and a component count of one skill directory and no command or agent directories, plus the client-owned install path and timestamps."
        },
        "invocation": {
          "result": "executed",
          "command": "python3.12 <client-home>/.grok/installed-plugins/<plugin-id>/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Exit status 0 and usage text for both entrypoints, credential-free and with no host argument, on CPython 3.12.13, run out of the client-owned copy rather than the source tree."
        }
      },
      "status": "works-directly",
      "reason": "Validated the portable manifest on its own terms and installed it from a local directory with no vendor-specific artifact added, then ran the package's entrypoints from the copy it owns."
    },
    {
      "name": "OpenCode",
      "version": "1.18.18",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "cp -R <skill> <client-home>/.agents/skills/",
          "evidence": "The client's own built-in configuration documents ~/.agents/skills as an auto-loaded external skill location. There is no install command for that path, so placement is a copy of the two portable skill directories into it."
        },
        "discovery": {
          "result": "executed",
          "command": "opencode debug skill",
          "evidence": "Both skills enumerated by name with their descriptions read from the portable frontmatter and their locations resolving to the placed SKILL.md files."
        },
        "load": {
          "result": "executed",
          "command": "opencode debug skill",
          "evidence": "The same command returns each skill's full parsed body, not merely its name — the complete SKILL.md content for unifi-network and unifi-protect — which is load proven rather than inferred, and it runs without credentials."
        },
        "invocation": {
          "result": "executed",
          "command": "python3.12 <client-home>/.agents/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Exit status 0 and usage text for both entrypoints, credential-free and with no host argument, on CPython 3.12.13, from the path the client auto-loads."
        }
      },
      "status": "works-directly",
      "reason": "Consumed the portable skill units as shipped from its own documented auto-load path, with no vendor-specific artifact added, and returned their parsed bodies as proof of load."
    },
    {
      "name": "Gemini CLI",
      "version": "0.44.1",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "gemini skills link <skill>",
          "evidence": "Prompted for local consent naming the link destination, then linked each portable skill directory as a symbolic link, confirmed by resolving both links back to the portable directories. What the client holds is the package's own bytes."
        },
        "discovery": {
          "result": "executed",
          "command": "gemini skills list --all",
          "evidence": "Both skills listed by name, each marked Enabled, with descriptions read from the portable frontmatter and locations pointing at the linked SKILL.md files. Two notices concern project agents and hooks in an untrusted folder, neither of which is a skill diagnostic."
        },
        "load": {
          "result": "executed",
          "command": "gemini skills list --all",
          "evidence": "The same command resolves each skill's frontmatter — name, description, enabled state — with no diagnostic against either skill. Injection into the session system prompt is not observable without credentials, so what is confirmed is definition load, not session injection."
        },
        "invocation": {
          "result": "executed",
          "command": "python3.12 <client-home>/.gemini/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Exit status 0 and usage text for both entrypoints, credential-free and with no host argument, on CPython 3.12.13, through the client-resolved symbolic links into the portable directories."
        }
      },
      "status": "works-directly",
      "reason": "Resolved and linked the portable skill units as shipped, holding the package's own bytes with no vendor-specific artifact added, and ran the entrypoints through the path it resolved."
    },
    {
      "name": "Muse",
      "version": "0.2.1",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "muse skills install <skill> --scope user",
          "evidence": "Each portable skill directory validated as-is with 'muse skills validate <skill>' and installed at user scope. Recorded rather than worked around: the portable package root is not an installable unit for this client, which refused it with 'skill package must contain SKILL.md', so the two skill directories are installed individually. No vendor artifact is added either way."
        },
        "discovery": {
          "result": "executed",
          "command": "muse skills list --source user",
          "evidence": "Both skills listed at user scope with activation on and descriptions read from the portable frontmatter."
        },
        "load": {
          "result": "executed",
          "command": "muse skills install <skill> --scope user --json",
          "evidence": "The client records a content digest and a per-file digest inventory for what it installed: unifi-network at content sha256 7998fad3a43c9d5eb0e2342906336eb4748c877e6fb937935534dea915d19be7 over 4 files, unifi-protect at content sha256 102418488b587cc5 over 4 files. Its inventory names scripts/_bundled/retry_backoff.py at sha256 9e1f2f17e9645f05, 11069 bytes, equal to the regenerated bundle in this repository — independent confirmation from a client's own bookkeeping that Fleet Core 0.25.2 reached the installed bytes."
        },
        "invocation": {
          "result": "executed",
          "command": "python3.12 <client-home>/.config/muse/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Exit status 0 and usage text for both entrypoints, credential-free and with no host argument, on CPython 3.12.13, from the client-owned installed copy."
        }
      },
      "status": "works-directly",
      "reason": "Validated and installed the portable skill units as shipped with no vendor-specific artifact added. The package root is not an installable unit for this client, which is a limitation of what it accepts as a unit rather than a rejection of the portable form, and the two units install cleanly."
    },
    {
      "name": "Agy",
      "version": "1.1.18",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "agy plugin install <package>",
          "evidence": "Validated the portable package root first with 'agy plugin validate <package>', reporting ok with skills 2 processed and agents, commands, mcpServers, and hooks each skipped as not found, then installed from the local path into a client-owned copy."
        },
        "discovery": {
          "result": "executed",
          "command": "agy plugin list",
          "evidence": "One import entry named unifi with a skills component list and an import timestamp."
        },
        "load": {
          "result": "executed",
          "command": "agy plugin validate <client-home>/.gemini/config/plugins/unifi",
          "evidence": "Re-validating the client-owned installed copy returned the same result as the source: ok, skills 2 processed, every other component absent. Validated separately, the com.infiquetra.claude client extension directory yielded skills 1 processed, agents 1 processed, and commands 1 processed converted to skills."
        },
        "invocation": {
          "result": "executed",
          "command": "python3.12 <client-home>/.gemini/config/plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Exit status 0 and usage text for both entrypoints, credential-free and with no host argument, on CPython 3.12.13, from the client-owned installed copy."
        }
      },
      "status": "works-directly",
      "reason": "Validated and installed the portable package root as shipped with no vendor-specific artifact added, and re-validated its own installed copy to the same result."
    },
    {
      "name": "Hermes",
      "version": "0.20.4",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "cp -R <skill> <client-home>/.hermes/skills/",
          "evidence": "The client's install subcommand accepts a remote identifier or an HTTP URL rather than a local path, so placement at profile scope is a copy of the two portable skill directories into the profile skills directory."
        },
        "discovery": {
          "result": "executed",
          "command": "hermes skills list",
          "evidence": "Both skills listed as local source, local trust, status enabled; the client's own tally reads 0 hub-installed, 0 builtin, 2 local — 2 enabled, 0 disabled, where the pre-placement baseline was 0 of each."
        },
        "load": {
          "result": "executed",
          "command": "hermes prompt-size --json",
          "evidence": "The client's own fresh-session prompt report, which it documents as running offline with no API call, resolves a skills index of 236 characters and 238 bytes where the pre-placement baseline was 0 and 0. That report is generated without credentials and without a live session, which is why it counts as load rather than as inventory."
        },
        "invocation": {
          "result": "executed",
          "command": "python3.12 <client-home>/.hermes/skills/unifi-network/scripts/unifi_network_client.py --help",
          "evidence": "Exit status 0 and usage text for both entrypoints, credential-free and with no host argument, on CPython 3.12.13, from profile scope."
        }
      },
      "status": "works-directly",
      "reason": "Consumed the portable skill units as shipped at profile scope with no vendor-specific artifact added, and proved load through its own offline prompt report rather than through inventory alone."
    }
  ]
}
```
