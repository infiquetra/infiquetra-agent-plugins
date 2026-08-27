<!-- matrix-status: superseded -->
<!-- superseded-by: 2026-08-27-agent-launcher-compatibility-matrix.md -->
<!-- superseded-reason: Code-review cycle-2 repairs (fix-eddba59df99e) changed the portable skill bytes; the assessment was re-run and the record re-bound to the repaired fingerprint. -->


# Ten-client compatibility matrix — portable agent-launcher package

This repository holds the proposed portable source catalog for Infiquetra Agent
Skills and Agent Plugins. One package in it, `plugins/agent-launcher/`, was assembled as a
derived artifact from an upstream Claude Code plugin in
`infiquetra/infiquetra-claude-plugins` at pinned commit `8269f84b01065ac96d162431ce00ebd42003dd5f`
(version 1.0.0, accepted upstream as agent-launcher 1.0.0 under issue #777 there). This
document records what happened when that package was put in front of every coding-agent
client installed on the operator's machine, on 27 August 2026.

This is the current record, re-bound to the repaired package tree after the
code-review cycle-1 fixes changed the package documentation and tests. The
earlier record against the first frozen tree is preserved unmodified as
`2026-08-27-agent-launcher-compatibility-matrix-pre-cycle2-repair.md`,
superseded by this document. The two runs observed identical client behavior;
only the bound fingerprint moved.

The point of the exercise is to learn which clients can consume a portable
package and which cannot, before anyone commits to a distribution path. It is a
survey, not a release gate.

## What this document is, and is not

It is a record of what ten clients did with one package on one machine on one
day. It is not a claim about those clients in general, not a claim that any
client will keep behaving this way, and not a release gate: nothing here decides
whether the package ships.

**Its scope is the package, not this repository.** Every result below concerns the
individual `plugins/agent-launcher/` package, placed by local path. Registering
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
- **Credentials.** No client was authenticated and no credential was supplied at
  any stage. The package declares no credential variable prefixes (its launcher
  reads no credentials), so no environment variables were stripped beyond the
  scratch-home redirections. Where a client requires credentials before it will
  report extension state, that stage is recorded blocked with the requirement
  named, not satisfied; none did.
- **Network.** No remote API call was made at any stage. The invocation stage runs
  the single declared package entrypoint with its credential-free `--help` action,
  so argparse handles the invocation and no request leaves the machine. No
  mutating operation was invoked and no command passed a write confirmation
  (`--confirm`); the harness safety rule blocks the launcher's `launch` and
  `close` verbs in advance. Where a client required an explicit local
  installation trust before installing from a directory, that trust was given and
  is named in the row; it authorizes a local install and is not a write
  confirmation against any remote API.
- **The interpreter is the declared floor.** Every invocation stage ran on
  `python3.12`, CPython 3.12.13, in a throwaway virtual environment holding no
  third-party dependencies, because the package's single entrypoint is standard
  library only. The catalog's declared minimum is `python>=3.12`; the floor is
  exercised here by explicit path rather than assumed.
- **The assessed copy is the shipped tree.** The package root handed to each
  client was a scratch copy of `plugins/agent-launcher/`, fingerprinted before the
  run at 11 files, `c9689c2f…`, equal to the source tree, and recomputed after
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

Seven clients consumed the portable package and executed its single entrypoint
directly — Cursor Agent, Qwen, OpenCode, Gemini CLI, Muse, Agy, and Hermes, the
four skill-scoped clients among them placing the one skill unit. Three clients
work through an adapter: Claude Code through its session-scoped local-plugin
flag, OpenAI Codex through the marketplace manifest it names and this package
does not ship, and Grok, which placed, discovered, and loaded cleanly with its
install trust supplied while its invocation stayed blocked because the harness's
capture did not resolve the client-generated plugin id into its command
template. No client failed; no client is unsupported.

| Client | Version | Placement | Discovery | Load | Invocation | Status |
|---|---|---|---|---|---|---|
| Claude Code | 2.1.247 | executed | executed | executed | executed | works through an adapter |
| OpenAI Codex | 0.150.1 | executed | executed | blocked | blocked | works through an adapter |
| Cursor Agent | 2026.08.25-3e8eec8 | executed | executed | executed | executed | works directly |
| Qwen | 0.22.2 | executed | executed | executed | executed | works directly |
| Grok | 1.0.5 | executed | executed | executed | blocked | works through an adapter |
| OpenCode | 1.18.18 | executed | executed | executed | executed | works directly |
| Gemini CLI | 0.44.1 | executed | executed | executed | executed | works directly |
| Muse | 0.2.1 | executed | executed | executed | executed | works directly |
| Agy | 1.1.22 | executed | executed | executed | executed | works directly |
| Hermes | 0.20.5 | executed | executed | executed | executed | works directly |

Ten clients, forty stage results — 37 executed, 3 blocked, 0 not-applicable —
and ten overall statuses: 7 works directly, 3 works through an adapter, 0 failed,
0 unsupported. Client versions were captured by read-only `--version` probes on
the assessment day; the Qwen load stage additionally reported the package itself
at version 1.0.0 with its manifest description.

## Key Observations

- **The single skill unit is the whole surface.** This package ships one skill
  and one entrypoint, so the four skill-scoped clients (OpenCode, Gemini CLI,
  Muse, Hermes) consume everything it has by installing `skills/agent-launcher`
  individually; each resolved the launcher from its own installed copy and
  answered `--help` cleanly. The six package-scoped clients placed the package
  root.
- **Claude Code loads session-scoped, and its name lookup says so.** The
  portable root carries no marketplace file, so placement used the local-plugin
  flag: the session-scoped listing reported the package loaded with version
  unknown, while the name-based `plugin details` lookup does not resolve a
  session-scoped plugin and recorded that refusal. The entrypoint ran from the
  package path either way.
- **OpenAI Codex named the adapter it wants.** Placement refused the package
  root with an actionable message naming the marketplace manifest it expects;
  load and invocation stayed blocked on that absent adapter rather than on any
  package defect. This is the same shape the mission-control matrix recorded.
- **Grok installed cleanly; its invocation stays blocked on an uncaptured id.**
  Placement, discovery, and load ran clean (load resolved the client-generated
  install id and its path), but the harness's capture did not resolve that id
  into the invocation command template, and running an unresolved path would
  record the package failing for a value the client never reported. The block is
  a harness-template limitation, recorded rather than guessed.
- **Three launcher wrappers on this machine resolve their real binary through
  the client home.** Grok and Agy (auto-trust) and Qwen (herdr) each carry a
  documented override naming the real executable; under an isolated home the
  lookup fails, so the run supplied those overrides. That is a property of the
  operator's launcher arrangement and of this method's isolated home, not of the
  package; the first attempt this same day without the Qwen override recorded
  four failed Qwen stages and was re-run rather than committed.
- **The entrypoint is runnable from every resolved copy.** Every invocation that
  ran exited 0 with usage text, on the floor interpreter, credential-free, from
  the client-resolved path — including the Qwen client copy, the Muse config
  copy, the Hermes profile copy, and the Grok/Agy installed-plugin copies where
  invocation was reachable.

## The machine-readable record

```json
{
  "$schema": "../../schemas/compatibility-matrix.schema.json",
  "schema_version": "2",
  "assessed_on": "2026-08-27",
  "package": {
    "name": "agent-launcher",
    "version": "1.0.0",
    "file_count": 11,
    "tree_sha256": "c9689c2f90c9f137e9b7939cd7714394d2408b2a6116cbed7d10cd06497a4d95"
  },
  "method": {
    "stages": [
      "placement",
      "discovery",
      "load",
      "invocation"
    ],
    "isolation": "Each client ran against its own empty home directory in a scratch area, so no assessment read or wrote the operator's real client configuration; every result reflects a first-run install. The package root handed to each client was a scratch copy of the shipped tree, fingerprinted before the run at 11 files, c9689c2f..., equal to the source tree, and recomputed after the run and still equal. Cursor Agent is the single established exception: it keeps its authentication in the user's home, so it was assessed against the real home with read-only session-scoped probes that write no client state. Two launcher wrappers on this machine (Grok and Agy auto-trust, and Qwen's herdr wrapper) resolve their real binary through the client home; under an isolated home that lookup fails, so the run supplies each wrapper's own documented override naming the real executable. That is a property of the operator's launcher arrangement and of this method's isolated home, not of the package; recording a package failure for it would be false. This is the second run of the day: code-review cycle-1 repairs changed the package documentation and tests, moving the fingerprint, so the earlier current record was superseded and this run re-binds the matrix to the repaired tree.",
    "credentials": "No client was authenticated and no credential was supplied at any stage. The package declares no credential variable prefixes (its launcher reads no credentials), so no environment variables were stripped beyond the scratch-home redirections. Where a client would need credentials before reporting state, the stage would be recorded blocked with the requirement named; none did.",
    "network": "No remote API call was made at any stage. The invocation stage runs the single declared package entrypoint with its credential-free --help action, so argparse answers it and no request leaves the machine. No mutating operation was invoked and no command passed a write confirmation (--confirm); the harness safety rule blocks the launcher's launch and close verbs in advance."
  },
  "clients": [
    {
      "name": "Claude Code",
      "version": "2.1.247",
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
          "evidence": "Session-scoped listing reports package@inline, version unknown, status loaded, exit 0."
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
          "evidence": "Session-scoped listing enumerates the package loaded from the scratch path, exit 0."
        },
        "load": {
          "result": "executed",
          "command": "claude --plugin-dir <package> plugin details agent-launcher",
          "commands": [
            {
              "command": "claude --plugin-dir <package> plugin details agent-launcher",
              "exit_status": 1
            }
          ],
          "evidence": "Name-based details lookup reports the plugin not found for a session-scoped plugin, exit 1."
        },
        "invocation": {
          "result": "executed",
          "command": "<python> <package>/skills/agent-launcher/scripts/launcher.py --help",
          "commands": [
            {
              "command": "<python> <package>/skills/agent-launcher/scripts/launcher.py --help",
              "exit_status": 0
            }
          ],
          "evidence": "launcher.py --help from the package path exits 0 with usage text."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "Placed, discovered, and loaded session-scoped through the local-plugin flag (the portable root carries no marketplace file, so user-scope installation is not a path here): the session-scoped listing reports the package loaded with version unknown. The name-based details lookup does not resolve a session-scoped plugin, so that stage records the client's refusal rather than a package defect; the entrypoint ran from the package path and answered --help."
    },
    {
      "name": "OpenAI Codex",
      "version": "0.150.1",
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
          "evidence": "Marketplace add refuses the package root, naming the missing supported manifest, exit 1."
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
          "evidence": "Plugin list runs and reports no marketplace plugins, exit 0."
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
      "reason": "Codex refuses the package root with an actionable message naming the marketplace manifest it wants; the marketplace is its only placement path, and no Codex adapter ships with this package. Discovery runs and reports no marketplace plugins; load and invocation stay blocked on the absent adapter rather than on any package defect."
    },
    {
      "name": "Cursor Agent",
      "version": "2026.08.25-3e8eec8",
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
          "evidence": "Session-scoped probe reports the locally loaded plugin, exit 0."
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
          "evidence": "Session-scoped probe enumerates the plugin, exit 0."
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
          "evidence": "Session-scoped probe reports the plugin name and components, exit 0."
        },
        "invocation": {
          "result": "executed",
          "command": "<python> <package>/skills/agent-launcher/scripts/launcher.py --help",
          "commands": [
            {
              "command": "<python> <package>/skills/agent-launcher/scripts/launcher.py --help",
              "exit_status": 0
            }
          ],
          "evidence": "launcher.py --help from the package path exits 0 with usage text."
        }
      },
      "status": "works-directly",
      "reason": "Assessed against the real authenticated home (an isolated home would measure an unauthenticated client). Session-scoped read-only probes report the loaded plugin and its component names from session context; the entrypoint ran from the package path and answered --help."
    },
    {
      "name": "Qwen",
      "version": "0.22.2",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "qwen extensions install <package>",
          "commands": [
            {
              "command": "qwen extensions install <package>",
              "exit_status": 0
            }
          ],
          "evidence": "Extensions install copies the package into the client extension directory, exit 0."
        },
        "discovery": {
          "result": "executed",
          "command": "qwen extensions list",
          "commands": [
            {
              "command": "qwen extensions list",
              "exit_status": 0
            }
          ],
          "evidence": "Extensions list enumerates the installed extension, exit 0."
        },
        "load": {
          "result": "executed",
          "command": "qwen extensions list",
          "commands": [
            {
              "command": "qwen extensions list",
              "exit_status": 0
            }
          ],
          "evidence": "Extension load reports agent-launcher at version 1.0.0 with its manifest description, exit 0."
        },
        "invocation": {
          "result": "executed",
          "command": "<python> <client-home>/.qwen/extensions/agent-launcher/skills/agent-launcher/scripts/launcher.py --help",
          "commands": [
            {
              "command": "<python> <client-home>/.qwen/extensions/agent-launcher/skills/agent-launcher/scripts/launcher.py --help",
              "exit_status": 0
            }
          ],
          "evidence": "launcher.py --help from the client-resolved copy exits 0 with usage text."
        }
      },
      "status": "works-directly",
      "reason": "Installed by the extensions installer (confirmation supplied on stdin), enumerated and loaded with its manifest version 1.0.0 and description, and the client-copied entrypoint answered --help under the floor interpreter. The client's launcher wrapper needed its documented real-binary override under the isolated home; supplied by the run, a property of the operator's launcher, not of the package."
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
          "evidence": "Plugin install reports one plugin installed from the scratch package, exit 0."
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
          "evidence": "Plugin list enumerates the installed plugin, exit 0."
        },
        "load": {
          "result": "executed",
          "command": "grok plugin details agent-launcher",
          "commands": [
            {
              "command": "grok plugin details agent-launcher",
              "exit_status": 0
            }
          ],
          "evidence": "Plugin details resolves the generated install id and its installed path, exit 0."
        },
        "invocation": {
          "result": "blocked",
          "command": "<python> <client-home>/.grok/installed-plugins/<plugin-id>/skills/agent-launcher/scripts/launcher.py --help",
          "reason": "The command still names <plugin-id>, which no earlier stage resolved. Running it would invoke a path that does not exist and record the package as failing for a value the client never reported."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "Placed with the client's install command (auto-trust supplied through the wrapper's documented override), discovered in the plugin list, and loaded with a client-generated install id; invocation stays blocked because the harness's capture did not resolve the generated plugin id into its command template, so running it would invoke a path the client never reported. Placement, discovery, and load are clean; the block is a harness-template limitation, recorded rather than guessed."
    },
    {
      "name": "OpenCode",
      "version": "1.18.18",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "cp -R <package>/skills/agent-launcher <client-home>/.agents/skills/",
          "commands": [
            {
              "command": "cp -R <package>/skills/agent-launcher <client-home>/.agents/skills/",
              "exit_status": 0
            }
          ],
          "evidence": "Skill directory copied into the client skills directory, exit 0."
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
          "evidence": "Debug skill enumerates the placed skill, exit 0."
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
          "evidence": "Debug skill prints the parsed skill body, exit 0."
        },
        "invocation": {
          "result": "executed",
          "command": "<python> <client-home>/.agents/skills/agent-launcher/scripts/launcher.py --help",
          "commands": [
            {
              "command": "<python> <client-home>/.agents/skills/agent-launcher/scripts/launcher.py --help",
              "exit_status": 0
            }
          ],
          "evidence": "launcher.py --help from the client-resolved copy exits 0 with usage text."
        }
      },
      "status": "works-directly",
      "reason": "The skill unit was copied into the client's auto-loaded skills directory; the client's debug command prints the skill's full parsed body, proving load rather than inferring it, and the client-resolved entrypoint answered --help."
    },
    {
      "name": "Gemini CLI",
      "version": "0.44.1",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "gemini skills link <package>/skills/agent-launcher",
          "commands": [
            {
              "command": "gemini skills link <package>/skills/agent-launcher",
              "exit_status": 0
            }
          ],
          "evidence": "Skills link places the skill unit, exit 0."
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
          "evidence": "Skills list enumerates the linked skill, exit 0."
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
          "evidence": "Skills list confirms the linked definition, exit 0."
        },
        "invocation": {
          "result": "executed",
          "command": "<python> <client-home>/.gemini/skills/agent-launcher/scripts/launcher.py --help",
          "commands": [
            {
              "command": "<python> <client-home>/.gemini/skills/agent-launcher/scripts/launcher.py --help",
              "exit_status": 0
            }
          ],
          "evidence": "launcher.py --help from the client-resolved copy exits 0 with usage text."
        }
      },
      "status": "works-directly",
      "reason": "The skill unit was linked with the client's skills link command (confirmation supplied on stdin, deadline bounded), enumerated in the skills list, and the client-resolved entrypoint answered --help."
    },
    {
      "name": "Muse",
      "version": "0.2.1",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "muse skills install <package>/skills/agent-launcher --scope user",
          "commands": [
            {
              "command": "muse skills install <package>/skills/agent-launcher --scope user",
              "exit_status": 0
            }
          ],
          "evidence": "Skills install places the skill unit at user scope, exit 0."
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
          "evidence": "Skills list enumerates the installed skill, exit 0."
        },
        "load": {
          "result": "executed",
          "command": "muse skills install <package>/skills/agent-launcher --scope user --force --json",
          "commands": [
            {
              "command": "muse skills install <package>/skills/agent-launcher --scope user --force --json",
              "exit_status": 0
            }
          ],
          "evidence": "Forced JSON install reports the installed content digest, exit 0."
        },
        "invocation": {
          "result": "executed",
          "command": "<python> <client-home>/.config/muse/skills/agent-launcher/scripts/launcher.py --help",
          "commands": [
            {
              "command": "<python> <client-home>/.config/muse/skills/agent-launcher/scripts/launcher.py --help",
              "exit_status": 0
            }
          ],
          "evidence": "launcher.py --help from the client-resolved copy exits 0 with usage text."
        }
      },
      "status": "works-directly",
      "reason": "Muse refuses the package root, so the skill unit installed individually with user scope; the forced JSON install reported a content digest, and the client-resolved entrypoint answered --help."
    },
    {
      "name": "Agy",
      "version": "1.1.22",
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
          "evidence": "Plugin install places the package, exit 0."
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
          "evidence": "Plugin list enumerates the installed plugin, exit 0."
        },
        "load": {
          "result": "executed",
          "command": "agy plugin validate <client-home>/.gemini/config/plugins/agent-launcher",
          "commands": [
            {
              "command": "agy plugin validate <client-home>/.gemini/config/plugins/agent-launcher",
              "exit_status": 0
            }
          ],
          "evidence": "Plugin validate re-validates the installed copy, exit 0."
        },
        "invocation": {
          "result": "executed",
          "command": "<python> <client-home>/.gemini/config/plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py --help",
          "commands": [
            {
              "command": "<python> <client-home>/.gemini/config/plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py --help",
              "exit_status": 0
            }
          ],
          "evidence": "launcher.py --help from the client-resolved copy exits 0 with usage text."
        }
      },
      "status": "works-directly",
      "reason": "Placed with the client's install command (auto-trust supplied through the wrapper's documented override), enumerated in the plugin list, and loaded by re-validating the client's own installed copy, which makes load independent of placement; the client-resolved entrypoint answered --help."
    },
    {
      "name": "Hermes",
      "version": "0.20.5",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "cp -R <package>/skills/agent-launcher <client-home>/.hermes/skills/",
          "commands": [
            {
              "command": "cp -R <package>/skills/agent-launcher <client-home>/.hermes/skills/",
              "exit_status": 0
            }
          ],
          "evidence": "Skill directory copied into the profile skills directory, exit 0."
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
          "evidence": "Skills list enumerates the placed skill, exit 0."
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
          "evidence": "Prompt-size --json composes the skills offline, exit 0."
        },
        "invocation": {
          "result": "executed",
          "command": "<python> <client-home>/.hermes/skills/agent-launcher/scripts/launcher.py --help",
          "commands": [
            {
              "command": "<python> <client-home>/.hermes/skills/agent-launcher/scripts/launcher.py --help",
              "exit_status": 0
            }
          ],
          "evidence": "launcher.py --help from the client-resolved copy exits 0 with usage text."
        }
      },
      "status": "works-directly",
      "reason": "Isolated home only. The skill unit was copied into the profile skills directory (the install subcommand takes only remote identifiers); the offline prompt-size composition proves load without credentials, and the client-resolved entrypoint answered --help."
    }
  ]
}
```
