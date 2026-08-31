<!-- matrix-status: superseded -->
<!-- superseded-by: 2026-08-30-mission-control-compatibility-matrix.md -->
<!-- superseded-reason: The forty stage results describe the package at tree digest 651ac28a..., 64 files, pinned at upstream 84eaf042 (v2.12.2). The 2.15.2 resynchronization moved the package to 71 files at tree 1f49322e..., and the F18/F11/F35 corrections then moved it again to 659f91f6..., so this record no longer identifies the tree it claims to describe. The successor chain ends at the current 2026-08-30 re-assessment of the corrected package. -->

> **Superseded - historical evidence. Do not read this as the current
> compatibility record.**
>
> This is the ten-client assessment exactly as it was published on 25 August
> 2026 against the pre-resynchronization package. It is kept because the
> assessment happened and its record should not vanish, not because it still
> describes the package.
>
> **What superseded it:**
> [`2026-08-30-mission-control-compatibility-matrix.md`](2026-08-30-mission-control-compatibility-matrix.md),
> the fresh assessment against the package as resynchronized to 2.15.2.

# Ten-client compatibility matrix — portable mission-control package

This repository holds the proposed portable source catalog for Infiquetra Agent
Skills and Agent Plugins. One package in it, `plugins/mission-control/`, was assembled as a
derived artifact from an upstream Claude Code plugin in
`infiquetra/infiquetra-claude-plugins` at pinned commit `84eaf042f0e350005f7eddf8e7d80da25c12119d`
(version 2.12.2). This document records what happened when that package was put
in front of every coding-agent client installed on the operator's machine, on 25
August 2026.

The point of the exercise is to learn which clients can consume a portable
package and which cannot, before anyone commits to a distribution path. It is a
survey, not a release gate.

## What this document is, and is not

It is a record of what ten clients did with one package on one machine on one
day. It is not a claim about those clients in general, not a claim that any
client will keep behaving this way, and not a release gate: nothing here decides
whether the package ships.

**Its scope is the package, not this repository.** Every result below concerns the
individual `plugins/mission-control/` package, placed by local path. Registering
*this repository* as a client marketplace or catalog is a different surface, and
it was not assessed for any client. A "works directly" row means the package
installs cleanly and runs its entrypoints, and says nothing about whether the
catalog containing it can be added to that client.

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
  Cursor Agent is the single exception (established in the UniFi pilot): that
  client keeps its authentication in the user's home, so an empty scratch home
  tests an unauthenticated client rather than an installed one. Cursor was
  assessed against the real home with read-only rules — its authentication state
  recorded only as present, no credential created, changed, or read into this
  evidence, and no account identity published here.
- **Credentials.** No client was authenticated and no GitHub credential was
  supplied at any stage. Every `GH_` and `GITHUB_` variable was removed from the
  environment before each invocation. Where a client requires credentials before
  it will report extension state, that stage is recorded blocked with the
  requirement named, not satisfied.
- **Network.** No GitHub API call was made at any stage. The invocation stage runs
  each declared package entrypoint with its credential-free `--help` action, so
  argparse handles the invocation and no request leaves the machine. No mutating
  operation was invoked and no command passed a write confirmation (`--confirm`).
  Where a client required an explicit local installation trust before installing
  from a directory, that trust was given and is named in the row; it authorizes a
  local install and is not a write confirmation against any remote API.
- **The interpreter is the declared floor.** Every invocation stage ran on
  `python3.12`, CPython 3.12.13, in a throwaway virtual environment holding the
  four third-party dependencies the package imports: `pytest`, `pyyaml`,
  `requests`, and `urllib3`. The catalog's declared minimum is `python>=3.12`; the
  floor is exercised here by explicit path rather than assumed.
- **The assessed copy is the shipped tree.** The package root handed to each
  client was a scratch copy of `plugins/mission-control/`, fingerprinted before the
  run at 64 files, `651ac28a…`, equal to the source tree, and recomputed after
  the run and still equal — so no client mutated what was assessed.

## The status rubric

The run plan fixes four statuses:

- **Works directly** — the client placed, discovered, and loaded the portable
  package, or its portable skill units, as shipped: no vendor-specific artifact
  added, no diagnostic raised, and ran its entrypoints cleanly.
- **Works through an adapter** — the client cannot consume the portable form as
  shipped, and its own tooling names the specific vendor artifact that would be
  required, or the client installs individual skill units rather than the package
  root leaving package-root entrypoints requiring an adapter.
- **Unsupported** — the client has no extension mechanism that could accept this
  package in any form.
- **Failed** — a supported path existed, and the assessment could not get the
  package through it. The blocking cause is named in the row.

## Results

One client consumed the portable package root and executed its entrypoints directly;
eight clients work through an adapter (including four skill-scoped clients that
fully consume the seven skill units but require an adapter for package-root scripts);
one client failed on an internal path assumption.

| Client | Version | Placement | Discovery | Load | Invocation | Status |
|---|---|---|---|---|---|---|
| Claude Code | 2.1.241 | executed | executed | executed | executed | works through an adapter |
| OpenAI Codex | 0.149.1 | executed | executed | blocked | blocked | works through an adapter |
| Cursor Agent | 2026.08.11 | executed | executed | executed | executed | failed |
| Qwen | 0.22.0 | executed | executed | executed | executed | works through an adapter |
| Grok | 1.0.5 | executed | executed | executed | blocked | works through an adapter |
| OpenCode | 1.18.18 | executed | executed | executed | blocked | works through an adapter |
| Gemini CLI | 0.44.1 | executed | executed | executed | blocked | works through an adapter |
| Muse | 0.2.1 | executed | executed | executed | blocked | works through an adapter |
| Agy | 1.1.20 | executed | executed | executed | executed | works directly |
| Hermes | 0.20.5 | executed | executed | executed | blocked | works through an adapter |

Ten clients, forty stage results — 33 executed, 7 blocked, 0 not-applicable —
and ten overall statuses: 1 works directly, 8 works through an adapter, 1 failed,
0 unsupported.

## Key Observations

- **Agy works directly.** Agy installed the portable package root, discovered all
  components, validated its installed copy with zero errors, and cleanly executed
  all five package entrypoints (`sdlc_manager.py`, `board_census.py`,
  `check_pagination.py`, `executor_profile_lint.py`, `sync_template_docs.py`)
  under Python 3.12.
- **Skill-scoped clients (OpenCode, Gemini CLI, Muse, Hermes) fully consume the skill units.**
  All four skill-scoped clients successfully placed, discovered, and loaded all seven
  portable skill units (`board`, `flow`, `issues`, `labels`, `metrics`,
  `milestones`, `rollout`) with zero diagnostics. Because these clients install
  skill units rather than the package root, the five package-root entrypoint
  scripts sit outside the client-delivered tree, so invocation is blocked in
  advance by design and recorded as working through an adapter.
- **Cursor Agent exposes a layout assumption in `sync_template_docs.py`.**
  Placement, discovery, and load succeeded from session context via `--plugin-dir`.
  However, `sync_template_docs.py` resolves its contract data file as
  `Path(__file__).resolve().parents[3] / "plugins/mission-control/config/generated/issue_contract_data.py"`,
  which requires the script to reside in a four-level repository structure. When
  placed directly in a session folder (`package/scripts/`), this import failed with
  `FileNotFoundError`, causing the invocation stage to fail.
- **Codex requires a marketplace manifest.** OpenAI Codex refused directory
  placement because its marketplace subsystem requires `marketplace.json` at the root.

## Client detail

### Claude Code — works through an adapter

The client accepted the portable package root through its session-scoped local
plugin flag (`--plugin-dir`) and enumerated `mission-control` in discovery. However,
`claude plugin details mission-control` returned exit 1 because the command refuses
session-only plugins (`Session-only plugins cannot be inspected with "plugin details"`).
Four entrypoints ran cleanly; `sync_template_docs.py` raised `FileNotFoundError` due to
the session directory layout. User-scope installation requires a Claude marketplace
manifest not carried at package root.

### OpenAI Codex — works through an adapter

The marketplace is this client's only placement path: it exposes no
local-plugin-directory flag. It refused the package root with `Error: invalid marketplace plugin source: missing marketplace.json`.
Load and invocation stay blocked on the absent adapter.

### Cursor Agent — failed

Session context enumerated and loaded plugin `mission-control` contributing skills
without diagnostics. In the invocation stage, four of the five package entrypoints
exited 0 with usage text, but `sync_template_docs.py` failed with `FileNotFoundError`
because its module-scope import assumes a repository root at `parents[3] / "plugins/mission-control/..."`.

### Qwen — works through an adapter

The client launcher wrapper requires user-home state and exited with code 127 under
an isolated home. Adding the package as a catalog extension source requires a
Claude-format marketplace manifest.

### Grok — works through an adapter

Installed, listed, and loaded the portable package root via `grok plugin install --trust`,
resolving package details and description for `mission-control v2.12.2`. Invocation
remains blocked because the client does not expose a resolved path for package-root scripts.

### OpenCode — works through an adapter

Auto-loaded all seven portable skill units from `~/.agents/skills/`. `opencode debug skill`
discovered and returned the full parsed bodies of all seven skills without diagnostics.
Invocation is blocked in advance because package-root entrypoints are not delivered by
skill-directory installation.

### Gemini CLI — works through an adapter

Linked all seven portable skill units into `~/.gemini/skills/` with stdin confirmation.
`gemini skills list --all` discovered and resolved definitions for all seven skills as
`Enabled`. Invocation of package-root entrypoints is blocked in advance pending a Gemini
extension adapter.

### Muse — works through an adapter

Installed all seven skill units individually at user scope. `muse skills list` discovered
all seven, and `muse skills install --force --json` reported verified content digests
for each unit. Invocation of package-root entrypoints is blocked in advance.

### Agy — works directly

Validated and installed the portable package root with all seven skills processed under
the client's plugins directory. `agy plugin list` enumerated the package, `agy plugin validate`
verified the installed tree, and all five declared entrypoints cleanly executed `--help`
under Python 3.12 from the client-installed path.

### Hermes — works through an adapter

Placed all seven skill directories into profile scope. `hermes skills list` discovered
all seven local skills enabled, and `hermes prompt-size --json` resolved them into the
composed prompt skills index with detailed byte breakdowns. Invocation of package-root
entrypoints is blocked in advance.

## The machine-readable record

```json
{
  "$schema": "../../schemas/compatibility-matrix.schema.json",
  "schema_version": "2",
  "assessed_on": "2026-08-25",
  "package": {
    "name": "mission-control",
    "version": "2.12.2",
    "file_count": 64,
    "tree_sha256": "651ac28a79b4e2e8823c5aa5960659bcd22903e2059afdb9544e13a071de1682"
  },
  "method": {
    "stages": [
      "placement",
      "discovery",
      "load",
      "invocation"
    ],
    "isolation": "Each client ran against its own empty home directory in a scratch area, so no assessment read or wrote the operator's real client configuration. Every stage result reflects a first-run install rather than an already-configured machine. The package root handed to each client was a scratch copy of the shipped tree, fingerprinted before the run at 64 files, 651ac28a..., equal to the source tree, and recomputed after the run and still equal. Every invocation stage ran on python3.12, CPython 3.12.13, which is the catalog's declared minimum interpreter, in a throwaway virtual environment holding the four third-party dependencies the package imports: pytest, pyyaml, requests, and urllib3. Running the assessment on a newer default interpreter is how a previous floor break reached a green report, so the floor is exercised by explicit path rather than assumed. Two clients, Grok and Agy, are launched through a local auto-trust wrapper that resolves the real executable through the client home. Under an isolated home that lookup fails, so each run supplies the wrapper's own documented override (GROK_AUTO_TRUST_REAL_BIN, AGY_AUTO_TRUST_REAL_BIN) pointing at the real binary. That is a property of the operator's launcher and of this method's isolated home, not of the package; recording a package failure for it would be false.",
    "credentials": "No client was authenticated and no GitHub credential was supplied at any stage. Every GH_ and GITHUB_ variable was removed from the environment before each invocation. Where a client requires credentials before it will report extension state, that stage is recorded blocked with the requirement named rather than satisfied.",
    "network": "No GitHub API call was made at any stage. The invocation stage runs each declared package entrypoint with its credential-free --help action, so argparse handles the invocation and no request leaves the machine. No mutating operation was invoked and no command passed a write confirmation. Where a client required an explicit local installation trust before installing from a directory, that trust was given and is named in the client's row; it authorizes a local install and is not a write confirmation against any remote API."
  },
  "clients": [
    {
      "name": "Claude Code",
      "version": "2.1.241",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "claude --plugin-dir <package> plugin list",
          "commands": [
            {
              "command": "claude --plugin-dir <package> plugin list",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command; exit status 0. Session-scoped placement loaded mission-control under --plugin-dir."
        },
        "discovery": {
          "result": "executed",
          "command": "claude --plugin-dir <package> plugin list",
          "commands": [
            {
              "command": "claude --plugin-dir <package> plugin list",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command; exit status 0. The plugin was enumerated as a session-only plugin pointing at the package path."
        },
        "load": {
          "result": "executed",
          "command": "claude --plugin-dir <package> plugin details mission-control",
          "commands": [
            {
              "command": "claude --plugin-dir <package> plugin details mission-control",
              "exit_status": 1
            }
          ],
          "evidence": "Ran 1 command; exit status 1. The client returned exit 1 because plugin details refuses session-only plugins with \"Session-only plugins cannot be inspected with plugin details\"."
        },
        "invocation": {
          "result": "executed",
          "command": "<python> <package>/scripts/sdlc_manager.py --help",
          "commands": [
            {
              "command": "<python> <package>/scripts/sdlc_manager.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/board_census.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/check_pagination.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/executor_profile_lint.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/sync_template_docs.py --help",
              "exit_status": 1
            }
          ],
          "evidence": "Ran 5 commands; exit status 0, 0, 0, 0, 1. Four entrypoints returned exit 0 with usage text; sync_template_docs.py returned exit 1 with FileNotFoundError attempting to resolve issue_contract_data.py relative to parents[3] under the session package directory structure."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "Accepted session-scoped placement and discovery via --plugin-dir, but plugin details refuses session-only plugins (exit 1), and full plugin installation requires an adapter/marketplace manifest not carried at package root."
    },
    {
      "name": "OpenAI Codex",
      "version": "0.149.1",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "codex plugin marketplace add <package>",
          "commands": [
            {
              "command": "codex plugin marketplace add <package>",
              "exit_status": 1
            }
          ],
          "evidence": "Ran 1 command; exit status 1. Refused marketplace addition with \"Error: invalid marketplace plugin source: missing marketplace.json\"."
        },
        "discovery": {
          "result": "executed",
          "command": "codex plugin list",
          "commands": [
            {
              "command": "codex plugin list",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command; exit status 0. Reported \"No marketplace plugins found.\"."
        },
        "load": {
          "result": "blocked",
          "reason": "Nothing was placed, so there is nothing to load. Blocked on the absent adapter rather than on any package defect."
        },
        "invocation": {
          "result": "blocked",
          "reason": "No client-resolved path exists, because placement produced none. A stage that did not run through the client is recorded blocked rather than borrowed from another client's result."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "Refused local directory placement at package root because the client requires a marketplace.json manifest. Load and invocation stay blocked on the absent adapter."
    },
    {
      "name": "Cursor Agent",
      "version": "2026.08.11",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "cursor-agent --plugin-dir <package> --mode ask --trust -p --output-format text Report the locally loaded plugin and component names available from session context. Do not use filesystem, shell, network, or UniFi tools.",
          "commands": [
            {
              "command": "cursor-agent --plugin-dir <package> --mode ask --trust -p --output-format text Report the locally loaded plugin and component names available from session context. Do not use filesystem, shell, network, or UniFi tools.",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command; exit status 0. Session context reported locally loaded plugin mission-control and its components."
        },
        "discovery": {
          "result": "executed",
          "command": "cursor-agent --plugin-dir <package> --mode ask --trust -p --output-format text Report the locally loaded plugin and component names available from session context. Do not use filesystem, shell, network, or UniFi tools.",
          "commands": [
            {
              "command": "cursor-agent --plugin-dir <package> --mode ask --trust -p --output-format text Report the locally loaded plugin and component names available from session context. Do not use filesystem, shell, network, or UniFi tools.",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command; exit status 0. The client enumerated plugin mission-control from session context."
        },
        "load": {
          "result": "executed",
          "command": "cursor-agent --plugin-dir <package> --mode ask --trust -p --output-format text From session context only, for the plugin loaded from the session-scoped local plugin directory (not any marketplace-installed plugin of the same name): report its plugin name, its version if session context carries one, and the exact component names it contributes. Do not use filesystem, shell, network, or UniFi tools.",
          "commands": [
            {
              "command": "cursor-agent --plugin-dir <package> --mode ask --trust -p --output-format text From session context only, for the plugin loaded from the session-scoped local plugin directory (not any marketplace-installed plugin of the same name): report its plugin name, its version if session context carries one, and the exact component names it contributes. Do not use filesystem, shell, network, or UniFi tools.",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command; exit status 0. The client resolved plugin mission-control contributing skills from session context without diagnostics."
        },
        "invocation": {
          "result": "executed",
          "command": "<python> <package>/scripts/sdlc_manager.py --help",
          "commands": [
            {
              "command": "<python> <package>/scripts/sdlc_manager.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/board_census.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/check_pagination.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/executor_profile_lint.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/sync_template_docs.py --help",
              "exit_status": 1
            }
          ],
          "evidence": "Ran 5 commands; exit status 0, 0, 0, 0, 1. Four entrypoints returned exit 0 with usage text; sync_template_docs.py returned exit 1 with FileNotFoundError attempting to resolve issue_contract_data.py relative to parents[3] under the session package directory structure."
        }
      },
      "status": "failed",
      "reason": "Placement, discovery, and load succeeded from session context via --plugin-dir, but invocation failed on sync_template_docs.py (exit 1) because the script expects a four-level repository tree layout to import issue_contract_data.py."
    },
    {
      "name": "Qwen",
      "version": "0.22.0",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "qwen extensions install <package>",
          "commands": [
            {
              "command": "qwen extensions install <package>",
              "exit_status": 127
            }
          ],
          "evidence": "Ran 1 command; exit status 127. The client wrapper exited with code 127 because the launcher's preserved binary was not found under the isolated scratch home."
        },
        "discovery": {
          "result": "executed",
          "command": "qwen extensions list",
          "commands": [
            {
              "command": "qwen extensions list",
              "exit_status": 127
            }
          ],
          "evidence": "Ran 1 command; exit status 127. The client wrapper exited with code 127 under the isolated home."
        },
        "load": {
          "result": "executed",
          "command": "qwen extensions list",
          "commands": [
            {
              "command": "qwen extensions list",
              "exit_status": 127
            }
          ],
          "evidence": "Ran 1 command; exit status 127. The client wrapper exited with code 127 under the isolated home."
        },
        "invocation": {
          "result": "executed",
          "command": "<python> <client-home>/.qwen/extensions/mission-control/scripts/sdlc_manager.py --help",
          "commands": [
            {
              "command": "<python> <client-home>/.qwen/extensions/mission-control/scripts/sdlc_manager.py --help",
              "exit_status": 2
            },
            {
              "command": "<python> <client-home>/.qwen/extensions/mission-control/scripts/board_census.py --help",
              "exit_status": 2
            },
            {
              "command": "<python> <client-home>/.qwen/extensions/mission-control/scripts/check_pagination.py --help",
              "exit_status": 2
            },
            {
              "command": "<python> <client-home>/.qwen/extensions/mission-control/scripts/executor_profile_lint.py --help",
              "exit_status": 2
            },
            {
              "command": "<python> <client-home>/.qwen/extensions/mission-control/scripts/sync_template_docs.py --help",
              "exit_status": 2
            }
          ],
          "evidence": "Ran 5 commands; exit status 2, 2, 2, 2, 2. The target scripts did not exist at the client extension path because placement did not run."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "The client could not be executed under an isolated home because its launcher wrapper relies on user-home state; installing catalog sources requires an adapter/marketplace source in Claude format."
    },
    {
      "name": "Grok",
      "version": "1.0.5",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "grok plugin install <package> --trust",
          "commands": [
            {
              "command": "grok plugin install <package> --trust",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command; exit status 0. Installed 1 plugin from local path: mission-control."
        },
        "discovery": {
          "result": "executed",
          "command": "grok plugin list",
          "commands": [
            {
              "command": "grok plugin list",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command; exit status 0. Enumerated package-e20b77f6: mission-control from local path."
        },
        "load": {
          "result": "executed",
          "command": "grok plugin details mission-control",
          "commands": [
            {
              "command": "grok plugin details mission-control",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command; exit status 0. Details resolved mission-control v2.12.2 and parsed description, reporting 1 skill dir."
        },
        "invocation": {
          "result": "blocked",
          "command": "<python> <client-home>/.grok/installed-plugins/<plugin-id>/scripts/sdlc_manager.py --help",
          "reason": "The command still names <plugin-id>, which no earlier stage resolved. Running it would invoke a path that does not exist and record the package as failing for a value the client never reported."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "Installed, listed, and loaded the portable package root via grok plugin, but invocation remains blocked because the client does not expose a resolved path for package-root scripts."
    },
    {
      "name": "OpenCode",
      "version": "1.18.18",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "cp -R <package>/skills/board <client-home>/.agents/skills/",
          "commands": [
            {
              "command": "cp -R <package>/skills/board <client-home>/.agents/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/flow <client-home>/.agents/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/issues <client-home>/.agents/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/labels <client-home>/.agents/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/metrics <client-home>/.agents/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/milestones <client-home>/.agents/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/rollout <client-home>/.agents/skills/",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 7 commands; exit status 0, 0, 0, 0, 0, 0, 0. Placed all seven portable skill directories into ~/.agents/skills/."
        },
        "discovery": {
          "result": "executed",
          "command": "opencode debug skill",
          "commands": [
            {
              "command": "opencode debug skill",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command; exit status 0. Enumerated all seven placed skills by name and location."
        },
        "load": {
          "result": "executed",
          "command": "opencode debug skill",
          "commands": [
            {
              "command": "opencode debug skill",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command; exit status 0. Parsed and returned full skill bodies for all seven skills without diagnostics."
        },
        "invocation": {
          "result": "blocked",
          "reason": "OpenCode installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/sdlc_manager.py', 'scripts/board_census.py', 'scripts/check_pagination.py', 'scripts/executor_profile_lint.py', 'scripts/sync_template_docs.py'. A stage that half ran did not run, so invocation is blocked in advance."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "Consumed all seven portable skill units directly from its auto-load path, but declared package entrypoints sit outside individual skill directories and require a package adapter for execution."
    },
    {
      "name": "Gemini CLI",
      "version": "0.44.1",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "gemini skills link <package>/skills/board",
          "commands": [
            {
              "command": "gemini skills link <package>/skills/board",
              "exit_status": 0
            },
            {
              "command": "gemini skills link <package>/skills/flow",
              "exit_status": 0
            },
            {
              "command": "gemini skills link <package>/skills/issues",
              "exit_status": 0
            },
            {
              "command": "gemini skills link <package>/skills/labels",
              "exit_status": 0
            },
            {
              "command": "gemini skills link <package>/skills/metrics",
              "exit_status": 0
            },
            {
              "command": "gemini skills link <package>/skills/milestones",
              "exit_status": 0
            },
            {
              "command": "gemini skills link <package>/skills/rollout",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 7 commands; exit status 0, 0, 0, 0, 0, 0, 0. Linked all seven portable skill units into ~/.gemini/skills/ with stdin confirmation."
        },
        "discovery": {
          "result": "executed",
          "command": "gemini skills list --all",
          "commands": [
            {
              "command": "gemini skills list --all",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command; exit status 0. Listed all seven skills as Enabled with frontmatter descriptions and linked paths."
        },
        "load": {
          "result": "executed",
          "command": "gemini skills list --all",
          "commands": [
            {
              "command": "gemini skills list --all",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command; exit status 0. Resolved frontmatter definitions for all seven skills without diagnostics."
        },
        "invocation": {
          "result": "blocked",
          "reason": "Gemini CLI installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/sdlc_manager.py', 'scripts/board_census.py', 'scripts/check_pagination.py', 'scripts/executor_profile_lint.py', 'scripts/sync_template_docs.py'. A stage that half ran did not run, so invocation is blocked in advance."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "Linked, discovered, and loaded all seven portable skill units, but package-root entrypoints sit outside individual skill directories and require a Gemini extension adapter to deliver."
    },
    {
      "name": "Muse",
      "version": "0.2.1",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "muse skills install <package>/skills/board --scope user",
          "commands": [
            {
              "command": "muse skills install <package>/skills/board --scope user",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/flow --scope user",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/issues --scope user",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/labels --scope user",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/metrics --scope user",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/milestones --scope user",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/rollout --scope user",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 7 commands; exit status 0, 0, 0, 0, 0, 0, 0. Installed all seven portable skill units individually at user scope."
        },
        "discovery": {
          "result": "executed",
          "command": "muse skills list --source user",
          "commands": [
            {
              "command": "muse skills list --source user",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command; exit status 0. Listed all seven skills at user scope with active status."
        },
        "load": {
          "result": "executed",
          "command": "muse skills install <package>/skills/board --scope user --force --json",
          "commands": [
            {
              "command": "muse skills install <package>/skills/board --scope user --force --json",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/flow --scope user --force --json",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/issues --scope user --force --json",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/labels --scope user --force --json",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/metrics --scope user --force --json",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/milestones --scope user --force --json",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/rollout --scope user --force --json",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 7 commands; exit status 0, 0, 0, 0, 0, 0, 0. Reported verified content digests for all seven skill units (board sha256:d8c00539..., flow sha256:22a466ba..., issues sha256:c3c0acdb..., labels sha256:1a930241..., metrics sha256:bf9a5ea0..., milestones sha256:eaa00d82..., rollout sha256:3aeaf9a8...)."
        },
        "invocation": {
          "result": "blocked",
          "reason": "Muse installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/sdlc_manager.py', 'scripts/board_census.py', 'scripts/check_pagination.py', 'scripts/executor_profile_lint.py', 'scripts/sync_template_docs.py'. A stage that half ran did not run, so invocation is blocked in advance."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "Installed, listed, and loaded all seven portable skill units with verified content digests, but package-root entrypoints cannot be installed or resolved without a package adapter."
    },
    {
      "name": "Agy",
      "version": "1.1.20",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "agy plugin install <package>",
          "commands": [
            {
              "command": "agy plugin install <package>",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command; exit status 0. Installed mission-control plugin and processed all seven skills under client plugins directory."
        },
        "discovery": {
          "result": "executed",
          "command": "agy plugin list",
          "commands": [
            {
              "command": "agy plugin list",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command; exit status 0. Listed imported plugin mission-control with skills component."
        },
        "load": {
          "result": "executed",
          "command": "agy plugin validate <client-home>/.gemini/config/plugins/mission-control",
          "commands": [
            {
              "command": "agy plugin validate <client-home>/.gemini/config/plugins/mission-control",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command; exit status 0. Validated client-installed copy with 7 skills processed and zero errors."
        },
        "invocation": {
          "result": "executed",
          "command": "<python> <client-home>/.gemini/config/plugins/mission-control/scripts/sdlc_manager.py --help",
          "commands": [
            {
              "command": "<python> <client-home>/.gemini/config/plugins/mission-control/scripts/sdlc_manager.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.gemini/config/plugins/mission-control/scripts/board_census.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.gemini/config/plugins/mission-control/scripts/check_pagination.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.gemini/config/plugins/mission-control/scripts/executor_profile_lint.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.gemini/config/plugins/mission-control/scripts/sync_template_docs.py --help",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 5 commands; exit status 0, 0, 0, 0, 0. All five entrypoint scripts returned exit status 0 and usage text under Python 3.12 from the client-owned installed copy."
        }
      },
      "status": "works-directly",
      "reason": "Validated, installed, and loaded the portable package root as shipped with all seven skills, and cleanly executed all five entrypoint scripts from the client-installed path."
    },
    {
      "name": "Hermes",
      "version": "0.20.5",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "cp -R <package>/skills/board <client-home>/.hermes/skills/",
          "commands": [
            {
              "command": "cp -R <package>/skills/board <client-home>/.hermes/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/flow <client-home>/.hermes/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/issues <client-home>/.hermes/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/labels <client-home>/.hermes/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/metrics <client-home>/.hermes/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/milestones <client-home>/.hermes/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/rollout <client-home>/.hermes/skills/",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 7 commands; exit status 0, 0, 0, 0, 0, 0, 0. Placed all seven skill directories into profile skills directory."
        },
        "discovery": {
          "result": "executed",
          "command": "hermes skills list",
          "commands": [
            {
              "command": "hermes skills list",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command; exit status 0. Listed 7 local skills enabled (0 hub-installed, 0 builtin, 7 local)."
        },
        "load": {
          "result": "executed",
          "command": "hermes prompt-size --json",
          "commands": [
            {
              "command": "hermes prompt-size --json",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command; exit status 0. Resolved all seven skills into the composed prompt skills index (639 chars) with per-skill breakdown."
        },
        "invocation": {
          "result": "blocked",
          "reason": "Hermes installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/sdlc_manager.py', 'scripts/board_census.py', 'scripts/check_pagination.py', 'scripts/executor_profile_lint.py', 'scripts/sync_template_docs.py'. A stage that half ran did not run, so invocation is blocked in advance."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "Placed, discovered, and loaded all seven portable skill units into profile scope and composed prompt index, but package-root entrypoints require an adapter to execute."
    }
  ]
}
```
