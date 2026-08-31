<!-- matrix-status: current -->

# Ten-client compatibility matrix — portable mission-control package (2.15.2)

This repository holds the portable source catalog for Infiquetra Agent Skills
and Agent Plugins. `plugins/mission-control/` is a derived artifact of the
upstream Claude Code plugin in `infiquetra/infiquetra-claude-plugins`, pinned at
commit `3b2b7083fdda8e39e213b5f4acf9f8301d60dd52` (version 2.15.2). This document
records what happened when the resynchronized package was put in front of every
coding-agent client installed on the operator's machine, on 30 August 2026.

It is a survey of what ten clients did with one package on one machine on one
day, not a release gate and not a claim about those clients in general. The
package was assessed exactly as it shipped after the resynchronization: 71
files, tree `1f49322e8412ac6b2ae0b1fbebf4a022ac2e53489be71aae674506a7613531f9`,
fingerprinted before and after the run and identical both times.

## How every client was assessed

The same four stages ran against every client, in the same order: placement
(can the package or its portable skill units be placed where the client
looks), discovery (does the client's own inventory enumerate what was
placed), load (does the client parse the placed definitions and hold them),
and invocation (does the safest credential-free, read-only entrypoint run
from the path this client resolved).

Held identical across all ten:

- **Isolation.** Nine clients ran against their own empty scratch home; Cursor
  Agent is the single exception and was assessed against the real authenticated
  home with read-only rules, because an isolated home strips its authentication.
- **Credentials.** No client was authenticated and no GitHub credential was
  supplied at any stage; every `GH_` and `GITHUB_` variable was stripped.
- **Network.** No GitHub API call was made at any stage; invocation ran each
  declared entrypoint with its credential-free `--help` action.
- **The interpreter is the declared floor.** Every invocation ran on CPython
  3.12.13 in a throwaway virtual environment holding pytest, pyyaml, requests,
  and urllib3, by explicit path.
- **Real binaries.** Grok and Agy ran through their real binaries supplied by
  `--real-binary` (the harness never infers them; `which` returns a wrapper).

## Client outcomes in one line each

| Client | Version | Outcome |
|---|---|---|
| Claude Code | 2.1.251 | Session-scoped placement and discovery via `--plugin-dir`; `plugin details` refuses session-only plugins by name; all five entrypoints exit 0 |
| OpenAI Codex | 0.151.0 | Refuses the package root (no marketplace manifest); load and invocation blocked on the absent adapter |
| Cursor Agent | 2026.08.25-3e8eec8 | Placement, discovery, load, and invocation all succeed from session context against the real home |
| Qwen | 0.22.3 | Environment failure: the isolated home's preserved Qwen wrapper exited 127 on every stage, so the real client never ran |
| Grok | 1.0.13 | Local plugin install resolves mission-control v2.15.2; invocation blocked on the install's internal plugin id |
| OpenCode | 1.18.25 | All seven skills placed and enumerated; package-root invocation blocked in advance (skills-only install) |
| Gemini CLI | 0.57.0 | All seven skills linked and discovered enabled; package-root invocation blocked in advance |
| Muse | 1.0.1 | All seven skills installed to user scope; package-root invocation blocked in advance |
| Agy | 1.1.22 | Plugin install, validate, and all five entrypoints at exit 0 from the client-resolved path |
| Hermes | 0.20.6 | All seven skills placed and resolved into the composed prompt; package-root invocation blocked in advance |

Coverage was mandatory; passing was not. Qwen's failure is an environment
condition of this machine's launcher wrapper under an isolated home, recorded
honestly rather than attributed to the package. No client-specific remediation
has been decided.

## The machine-readable record

```json
{
  "$schema": "../../schemas/compatibility-matrix.schema.json",
  "schema_version": "2",
  "assessed_on": "2026-08-30",
  "package": {
    "name": "mission-control",
    "version": "2.15.2",
    "file_count": 71,
    "tree_sha256": "1f49322e8412ac6b2ae0b1fbebf4a022ac2e53489be71aae674506a7613531f9"
  },
  "method": {
    "stages": [
      "placement",
      "discovery",
      "load",
      "invocation"
    ],
    "isolation": "Each client was handed its own fresh copy of the shipped tree, at 71 files, fingerprinted before and after that client ran. Every copy was unchanged afterwards, so no client added a vendor artifact to the package.",
    "credentials": "No client was authenticated and no GitHub credential was supplied at any stage. Every GH_ and GITHUB_ variable was removed from the environment before each invocation. Where a client requires credentials before it will report extension state, that stage is recorded blocked with the requirement named rather than satisfied.",
    "network": "No GitHub API call was made at any stage. The invocation stage runs each declared package entrypoint with its credential-free --help action on the floor interpreter, so no request leaves the machine. No mutating operation was invoked and no command passed a write confirmation."
  },
  "clients": [
    {
      "name": "Claude Code",
      "version": "2.1.251",
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
          "evidence": "Session-only plugin enumerated under --plugin-dir at exit 0."
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
          "evidence": "Session-only plugin enumerated under --plugin-dir at exit 0."
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
          "evidence": "exit 1: the client refuses session-only plugins by name; the package is loaded session-scoped, not installed."
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
              "exit_status": 0
            }
          ],
          "evidence": "All five entrypoints executed --help at exit 0 on python3.12."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "Accepted session-scoped placement and discovery via --plugin-dir (plugin list enumerates the package at exit 0), but `plugin details mission-control` refuses session-only plugins by name (exit 1). All five entrypoints executed --help at exit 0 on the floor interpreter from the package path."
    },
    {
      "name": "OpenAI Codex",
      "version": "0.151.0",
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
          "evidence": "exit 1: marketplace root does not contain a supported manifest; the portable package root carries no marketplace file."
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
          "evidence": "exit 0: no marketplace plugins found."
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
      "reason": "Refused local directory placement: `plugin marketplace add` reports the marketplace root does not contain a supported manifest (exit 1), and discovery lists no marketplace plugins. Load and invocation are blocked on the absent adapter rather than on any package defect."
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
          "evidence": "Session-context response at exit 0 via --plugin-dir against the real authenticated home."
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
          "evidence": "Session-context response at exit 0 enumerating the plugin."
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
          "evidence": "Session-context response at exit 0: plugin name mission-control; the session copy carries no version and the marketplace copy of the same name reads 2.15.2."
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
              "exit_status": 0
            }
          ],
          "evidence": "All five entrypoints executed --help at exit 0 on python3.12."
        }
      },
      "status": "works-directly",
      "reason": "Placement, discovery, and load succeeded from session context via --plugin-dir against the real authenticated home; the load response reports the session copy and notes the marketplace copy of the same name reads 2.15.2. All five entrypoints executed --help at exit 0 on the floor interpreter."
    },
    {
      "name": "Qwen",
      "version": "0.22.3",
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
          "evidence": "exit 127: preserved Qwen executable missing or not executable under the isolated home; the real client never ran."
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
          "evidence": "exit 127: preserved Qwen executable missing or not executable under the isolated home; the real client never ran."
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
          "evidence": "exit 127: preserved Qwen executable missing or not executable under the isolated home; the real client never ran."
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
          "evidence": "exit 2: the extension path was never placed, so the interpreter could not open the entrypoint scripts."
        }
      },
      "status": "failed",
      "reason": "Every stage exited 127: the isolated home's preserved Qwen wrapper was missing or not executable, so the real client never ran; invocation then could not open the extension path placement never produced (exit 2). This is an environment condition, not a package result, and the client was not actually exercised."
    },
    {
      "name": "Grok",
      "version": "1.0.13",
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
          "evidence": "exit 0: Installed 1 plugin(s): mission-control."
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
          "evidence": "exit 0: plugin list resolves the install id with kind local."
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
          "evidence": "exit 0: plugin details reports mission-control v2.15.2."
        },
        "invocation": {
          "result": "blocked",
          "command": "<python> <client-home>/.grok/installed-plugins/<plugin-id>/scripts/sdlc_manager.py --help",
          "reason": "The command still names <plugin-id>, which no earlier stage resolved. Running it would invoke a path that does not exist and record the package as failing for a value the client never reported."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "Placed the package as a local plugin (install --trust, exit 0); plugin list resolves the install id and plugin details reports mission-control v2.15.2 with kind local. Invocation is blocked: the resolved plugin id is internal to the install and no earlier stage resolved it to a path the harness may invoke."
    },
    {
      "name": "OpenCode",
      "version": "1.18.25",
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
          "evidence": "All seven skill directories copied to the skills scope, exit 0 each."
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
          "evidence": "exit 0: debug skill enumerates all seven placed skills."
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
          "evidence": "exit 0: debug skill enumerates all seven placed skills."
        },
        "invocation": {
          "result": "blocked",
          "reason": "OpenCode installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/sdlc_manager.py', 'scripts/board_census.py', 'scripts/check_pagination.py', 'scripts/executor_profile_lint.py', 'scripts/sync_template_docs.py'. A stage that half ran did not run, so invocation is blocked in advance."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "All seven skill directories were placed under the skills scope (exit 0 each) and `debug skill` enumerates all seven. Invocation is blocked in advance: OpenCode installs skill units rather than the package, so declared entrypoints outside every declared skill unit have no client-resolved path."
    },
    {
      "name": "Gemini CLI",
      "version": "0.57.0",
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
          "evidence": "Each skills link exited 0 after its interactive prompt was answered; seven skills linked."
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
          "evidence": "exit 0: all seven discovered enabled."
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
          "evidence": "exit 0: all seven discovered enabled."
        },
        "invocation": {
          "result": "blocked",
          "reason": "Gemini CLI installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/sdlc_manager.py', 'scripts/board_census.py', 'scripts/check_pagination.py', 'scripts/executor_profile_lint.py', 'scripts/sync_template_docs.py'. A stage that half ran did not run, so invocation is blocked in advance."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "All seven skills were linked (each `skills link` exited 0 after its interactive prompt was answered) and `skills list --all` discovers them enabled. Invocation is blocked in advance: Gemini installs skill units rather than the package."
    },
    {
      "name": "Muse",
      "version": "1.0.1",
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
          "evidence": "All seven installed to user scope, exit 0 each."
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
          "evidence": "exit 0: skills list --source user shows all seven with activation on."
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
          "evidence": "exit 0: --force --json reinstall reports each installed id."
        },
        "invocation": {
          "result": "blocked",
          "reason": "Muse installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/sdlc_manager.py', 'scripts/board_census.py', 'scripts/check_pagination.py', 'scripts/executor_profile_lint.py', 'scripts/sync_template_docs.py'. A stage that half ran did not run, so invocation is blocked in advance."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "All seven skills were installed to user scope and listed with activation on; the --force --json reinstall resolves each installed id at exit 0. Invocation is blocked in advance: Muse installs skill units rather than the package."
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
          "evidence": "exit 0: 7 skills processed."
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
          "evidence": "exit 0: plugin list imports mission-control."
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
          "evidence": "exit 0: validate resolves the plugin directory."
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
          "evidence": "All five entrypoints executed --help at exit 0 from the client-resolved install path on python3.12."
        }
      },
      "status": "works-directly",
      "reason": "Plugin install processed all seven skills (exit 0), plugin list imports mission-control, and validate resolves the plugin directory cleanly. All five entrypoints executed --help at exit 0 from the client-resolved install path on the floor interpreter. The auto-trust wrapper emitted its unreadable-settings warning under the isolated home; the real binary was supplied, so the run is real."
    },
    {
      "name": "Hermes",
      "version": "0.20.6",
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
          "evidence": "All seven skill directories placed into profile scope, exit 0 each."
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
          "evidence": "exit 0: skills list shows the seven installed skills."
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
          "evidence": "exit 0: prompt-size --json resolves the skills into the composed prompt with a skills index."
        },
        "invocation": {
          "result": "blocked",
          "reason": "Hermes installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/sdlc_manager.py', 'scripts/board_census.py', 'scripts/check_pagination.py', 'scripts/executor_profile_lint.py', 'scripts/sync_template_docs.py'. A stage that half ran did not run, so invocation is blocked in advance."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "All seven skill directories were placed into profile scope (exit 0 each); `skills list` discovers them and `prompt-size --json` resolves them into the composed prompt with a skills index. Invocation of package-root entrypoints is blocked in advance."
    }
  ]
}
```
