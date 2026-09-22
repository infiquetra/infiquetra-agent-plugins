<!-- matrix-status: current -->

# Ten-client compatibility matrix — portable saga package (1.2.2)

This repository holds the portable source catalog for Infiquetra Agent Skills
and Agent Plugins. `plugins/saga/` is authored and maintained
here. This document records what happened when the shipped package —
245 files, tree `ff0c1bff5084848ec2da540379e6e5e193de7ac617fb07b1b41c4944799dc699` — was put in front
of every coding-agent client installed on the operator's machine, on
2026-09-22.

It is a survey of what ten clients did with one package on one machine on one
day. It is not a release gate and not a claim about those clients in general.
The package was fingerprinted before and after the run and was identical both
times.

## How every client was assessed

The same four stages ran against every client, in the same order: placement
(can the package or its portable skill units be placed where the client
looks), discovery (does the client's own inventory enumerate what was placed),
load (does the client parse the placed definitions and hold them), and
invocation (does the declared credential-free entrypoint run from the path
this client resolved).

Held identical across all ten:

- **Isolation.** Each client was handed its own fresh copy of the shipped tree, at 245 files, fingerprinted before and after that client ran. Every copy was unchanged afterwards, so no client added a vendor artifact to the package. Nine clients ran against
  their own empty scratch home; Cursor Agent is the single exception and was
  assessed against the real authenticated home, because an isolated home
  strips its authentication and measures a different client.
- **Credentials.** The harness removed every variable matching `GH_`, `GITHUB_`, `TYPESAFE_` from every subprocess environment before each stage. Nine clients ran unauthenticated in their own empty scratch homes. Cursor Agent ran against the operator's real authenticated home by design, because an isolated home strips its authentication and produces a false failure; its authentication state is recorded only as present. No credential was created, changed, or read into this evidence, and no account identity is published here.
- **Network.** The invocation stage runs each declared entrypoint's credential-free `--help` action, which parses arguments and exits without a network call. The other three stages run each client's own commands, so a client that reaches its own service does so on its own account; Cursor Agent's three stages are model prompts, which is why it is the one client assessed against the real authenticated home.
- **The interpreter is the declared floor.** Every invocation ran on CPython
  3.14.7 by explicit path, the interpreter this machine resolves as `python3`.
  Every declared entrypoint answers `--help` on it with no third-party import.
- **Real binaries.** Grok and Agy ran through their real binaries supplied by
  `--real-binary`. The harness never infers those, because `which` returns the
  wrapper rather than the executable behind it. Qwen's real binary was supplied
  by exported override, which the harness does not declare itself.

## The status rubric

| Status | Meaning |
|---|---|
| `works-directly` | Placement, discovery, load, and invocation all ran through the client and every command exited 0. |
| `works-through-an-adapter` | The client engaged with the package and could not fully consume it. One or more stages are blocked or refused on a client-specific requirement rather than on a package defect. |
| `unsupported` | Nothing ran at all, or the client changed the copy it was handed and the row carries no classification. |
| `failed` | The client placed and loaded the package, and the package's own entrypoint then exited non-zero. |

## Results

In one sentence: **4 clients work directly, 6 work through an adapter, 0 failed, and 0 are unsupported.**

| Client | Version | Status | Placement | Discovery | Load | Invocation |
|---|---|---|---|---|---|---|
| Claude Code | 2.1.280 | works-directly | executed | executed | executed | executed |
| OpenAI Codex | 0.155.1 | works-through-an-adapter | executed | executed | blocked | blocked |
| Cursor Agent | 2026.09.18-9a7762b | works-directly | executed | executed | executed | executed |
| Qwen | 0.24.4 | works-directly | executed | executed | executed | executed |
| Grok | 1.0.40 | works-through-an-adapter | executed | executed | executed | blocked |
| OpenCode | 2.0.13 | works-through-an-adapter | executed | executed | executed | blocked |
| Gemini CLI | 0.57.0 | works-through-an-adapter | executed | executed | executed | blocked |
| Muse | 1.3.0 | works-through-an-adapter | executed | executed | executed | blocked |
| Agy | 1.2.7 | works-directly | executed | executed | executed | executed |
| Hermes | 0.21.3 | works-through-an-adapter | executed | executed | executed | blocked |

## Client outcomes

| Client | Outcome |
|---|---|
| Claude Code | All four stages ran through this client and every command exited 0: placement, discovery, load, and invocation of 12 declared entrypoint(s) from the path this client resolved. |
| OpenAI Codex | The client engaged with the package and could not fully consume it. Executed: placement, discovery. Blocked: load, invocation. Exited non-zero at: placement. At placement, the client refused the package root and named the manifest it requires. load: Nothing was placed, so there is nothing to load. invocation: No client-resolved path exists, because placement produced none. |
| Cursor Agent | All four stages ran through this client and every command exited 0: placement, discovery, load, and invocation of 12 declared entrypoint(s) from the path this client resolved. |
| Qwen | All four stages ran through this client and every command exited 0: placement, discovery, load, and invocation of 12 declared entrypoint(s) from the path this client resolved. |
| Grok | The client engaged with the package and could not fully consume it. Executed: placement, discovery, load. Blocked: invocation. invocation: The command still names <plugin-id>, which no earlier stage resolved. |
| OpenCode | The client engaged with the package and could not fully consume it. Executed: placement, discovery, load. Blocked: invocation. Exited non-zero at: discovery, load. At discovery, the client reported the subcommand this stage uses as unknown. At load, the client reported the subcommand this stage uses as unknown. invocation: OpenCode installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/admission.py', 'scripts/build_loop.py', 'scripts/intent_envelope.py', 'scripts/lifecycle_state.py', 'scripts/merge_turn.py', 'scripts/parse_issue.py', 'scripts/qa_strategies.py', 'scripts/release_step.py', 'scripts/review_roster.py', 'scripts/run_record.py', 'scripts/saga.py', 'scripts/shaping_judgments.py'. |
| Gemini CLI | The client engaged with the package and could not fully consume it. Executed: placement, discovery, load. Blocked: invocation. invocation: Gemini CLI installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/admission.py', 'scripts/build_loop.py', 'scripts/intent_envelope.py', 'scripts/lifecycle_state.py', 'scripts/merge_turn.py', 'scripts/parse_issue.py', 'scripts/qa_strategies.py', 'scripts/release_step.py', 'scripts/review_roster.py', 'scripts/run_record.py', 'scripts/saga.py', 'scripts/shaping_judgments.py'. |
| Muse | The client engaged with the package and could not fully consume it. Executed: placement, discovery, load. Blocked: invocation. invocation: Muse installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/admission.py', 'scripts/build_loop.py', 'scripts/intent_envelope.py', 'scripts/lifecycle_state.py', 'scripts/merge_turn.py', 'scripts/parse_issue.py', 'scripts/qa_strategies.py', 'scripts/release_step.py', 'scripts/review_roster.py', 'scripts/run_record.py', 'scripts/saga.py', 'scripts/shaping_judgments.py'. |
| Agy | All four stages ran through this client and every command exited 0: placement, discovery, load, and invocation of 12 declared entrypoint(s) from the path this client resolved. |
| Hermes | The client engaged with the package and could not fully consume it. Executed: placement, discovery, load. Blocked: invocation. invocation: Hermes installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/admission.py', 'scripts/build_loop.py', 'scripts/intent_envelope.py', 'scripts/lifecycle_state.py', 'scripts/merge_turn.py', 'scripts/parse_issue.py', 'scripts/qa_strategies.py', 'scripts/release_step.py', 'scripts/review_roster.py', 'scripts/run_record.py', 'scripts/saga.py', 'scripts/shaping_judgments.py'. |

Coverage was mandatory; passing was not. Every reason above is derived from the
stage results this run recorded. No stage result was carried over from an
earlier assessment, and no blocked stage was read as a satisfied one. The run's
private transcript holds each command's raw output; it is operator-only, is not
committed, and is not quoted here.

## The machine-readable record

```json
{
  "$schema": "../../schemas/compatibility-matrix.schema.json",
  "schema_version": "2",
  "assessed_on": "2026-09-22",
  "package": {
    "name": "saga",
    "version": "1.2.2",
    "file_count": 245,
    "tree_sha256": "ff0c1bff5084848ec2da540379e6e5e193de7ac617fb07b1b41c4944799dc699"
  },
  "method": {
    "stages": [
      "placement",
      "discovery",
      "load",
      "invocation"
    ],
    "isolation": "Each client was handed its own fresh copy of the shipped tree, at 245 files, fingerprinted before and after that client ran. Every copy was unchanged afterwards, so no client added a vendor artifact to the package.",
    "credentials": "The harness removed every variable matching `GH_`, `GITHUB_`, `TYPESAFE_` from every subprocess environment before each stage. Nine clients ran unauthenticated in their own empty scratch homes. Cursor Agent ran against the operator's real authenticated home by design, because an isolated home strips its authentication and produces a false failure; its authentication state is recorded only as present. No credential was created, changed, or read into this evidence, and no account identity is published here.",
    "network": "The invocation stage runs each declared entrypoint's credential-free `--help` action, which parses arguments and exits without a network call. The other three stages run each client's own commands, so a client that reaches its own service does so on its own account; Cursor Agent's three stages are model prompts, which is why it is the one client assessed against the real authenticated home."
  },
  "clients": [
    {
      "name": "Claude Code",
      "version": "2.1.280",
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
          "evidence": "Ran 1 command(s); exit status 0. The client's output named the package name, version 1.2.2, 1 of 13 declared skill unit(s)."
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
          "evidence": "Ran 1 command(s); exit status 0. The client's output named the package name, version 1.2.2, 1 of 13 declared skill unit(s)."
        },
        "load": {
          "result": "executed",
          "command": "claude --plugin-dir <package> plugin details saga",
          "commands": [
            {
              "command": "claude --plugin-dir <package> plugin details saga",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command(s); exit status 0. The client's output named the package name, version 1.2.2, 13 of 13 declared skill unit(s)."
        },
        "invocation": {
          "result": "executed",
          "command": "<python> <package>/scripts/admission.py --help",
          "commands": [
            {
              "command": "<python> <package>/scripts/admission.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/build_loop.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/intent_envelope.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/lifecycle_state.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/merge_turn.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/parse_issue.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/qa_strategies.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/release_step.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/review_roster.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/run_record.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/saga.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/shaping_judgments.py --help",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 12 command(s); exit status 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0. The client's output named the package name."
        }
      },
      "status": "works-directly",
      "reason": "All four stages ran through this client and every command exited 0: placement, discovery, load, and invocation of 12 declared entrypoint(s) from the path this client resolved."
    },
    {
      "name": "OpenAI Codex",
      "version": "0.155.1",
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
          "evidence": "Ran 1 command(s); exit status 1. The client refused the package root and named the manifest it requires. The client's output named the package name, 1 of 13 declared skill unit(s)."
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
          "evidence": "Ran 1 command(s); exit status 0. The client's output named 0 of 13 declared skill unit(s)."
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
      "reason": "The client engaged with the package and could not fully consume it. Executed: placement, discovery. Blocked: load, invocation. Exited non-zero at: placement. At placement, the client refused the package root and named the manifest it requires. load: Nothing was placed, so there is nothing to load. invocation: No client-resolved path exists, because placement produced none."
    },
    {
      "name": "Cursor Agent",
      "version": "2026.09.18-9a7762b",
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
          "evidence": "Ran 1 command(s); exit status 0. The client's output named the package name, 13 of 13 declared skill unit(s)."
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
          "evidence": "Ran 1 command(s); exit status 0. The client's output named the package name, 13 of 13 declared skill unit(s)."
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
          "evidence": "Ran 1 command(s); exit status 0. The client's output named the package name, 13 of 13 declared skill unit(s)."
        },
        "invocation": {
          "result": "executed",
          "command": "<python> <package>/scripts/admission.py --help",
          "commands": [
            {
              "command": "<python> <package>/scripts/admission.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/build_loop.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/intent_envelope.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/lifecycle_state.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/merge_turn.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/parse_issue.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/qa_strategies.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/release_step.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/review_roster.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/run_record.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/saga.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <package>/scripts/shaping_judgments.py --help",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 12 command(s); exit status 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0. The client's output named the package name."
        }
      },
      "status": "works-directly",
      "reason": "All four stages ran through this client and every command exited 0: placement, discovery, load, and invocation of 12 declared entrypoint(s) from the path this client resolved."
    },
    {
      "name": "Qwen",
      "version": "0.24.4",
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
          "evidence": "Ran 1 command(s); exit status 0. The client's output named the package name, 13 of 13 declared skill unit(s)."
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
          "evidence": "Ran 1 command(s); exit status 0. The client's output named the package name, version 1.2.2, 13 of 13 declared skill unit(s)."
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
          "evidence": "Ran 1 command(s); exit status 0. The client's output named the package name, version 1.2.2, 13 of 13 declared skill unit(s)."
        },
        "invocation": {
          "result": "executed",
          "command": "<python> <client-home>/.qwen/extensions/saga/scripts/admission.py --help",
          "commands": [
            {
              "command": "<python> <client-home>/.qwen/extensions/saga/scripts/admission.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.qwen/extensions/saga/scripts/build_loop.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.qwen/extensions/saga/scripts/intent_envelope.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.qwen/extensions/saga/scripts/lifecycle_state.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.qwen/extensions/saga/scripts/merge_turn.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.qwen/extensions/saga/scripts/parse_issue.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.qwen/extensions/saga/scripts/qa_strategies.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.qwen/extensions/saga/scripts/release_step.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.qwen/extensions/saga/scripts/review_roster.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.qwen/extensions/saga/scripts/run_record.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.qwen/extensions/saga/scripts/saga.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.qwen/extensions/saga/scripts/shaping_judgments.py --help",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 12 command(s); exit status 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0. The client's output named the package name."
        }
      },
      "status": "works-directly",
      "reason": "All four stages ran through this client and every command exited 0: placement, discovery, load, and invocation of 12 declared entrypoint(s) from the path this client resolved."
    },
    {
      "name": "Grok",
      "version": "1.0.40",
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
          "evidence": "Ran 1 command(s); exit status 0. The client's output named the package name, 1 of 13 declared skill unit(s)."
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
          "evidence": "Ran 1 command(s); exit status 0. The client's output named the package name, 1 of 13 declared skill unit(s)."
        },
        "load": {
          "result": "executed",
          "command": "grok plugin details saga",
          "commands": [
            {
              "command": "grok plugin details saga",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command(s); exit status 0. The client's output named the package name, version 1.2.2, 3 of 13 declared skill unit(s)."
        },
        "invocation": {
          "result": "blocked",
          "command": "<python> <client-home>/.grok/installed-plugins/<plugin-id>/scripts/admission.py --help",
          "reason": "The command still names <plugin-id>, which no earlier stage resolved. Running it would invoke a path that does not exist and record the package as failing for a value the client never reported."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "The client engaged with the package and could not fully consume it. Executed: placement, discovery, load. Blocked: invocation. invocation: The command still names <plugin-id>, which no earlier stage resolved."
    },
    {
      "name": "OpenCode",
      "version": "2.0.13",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "cp -R <package>/skills/brainstorm <client-home>/.agents/skills/",
          "commands": [
            {
              "command": "cp -R <package>/skills/brainstorm <client-home>/.agents/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/code-review <client-home>/.agents/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/doc-review <client-home>/.agents/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/founder-review <client-home>/.agents/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/ideate <client-home>/.agents/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/investigate <client-home>/.agents/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/office-hours <client-home>/.agents/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/plan <client-home>/.agents/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/qa <client-home>/.agents/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/retro <client-home>/.agents/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/spec <client-home>/.agents/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/strategy <client-home>/.agents/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/work <client-home>/.agents/skills/",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 13 command(s); exit status 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0. The command produced no output, so its exit status is the whole result."
        },
        "discovery": {
          "result": "executed",
          "command": "opencode debug skill",
          "commands": [
            {
              "command": "opencode debug skill",
              "exit_status": 1
            }
          ],
          "evidence": "Ran 1 command(s); exit status 1. The client reported the subcommand this stage uses as unknown. The client's output named 0 of 13 declared skill unit(s)."
        },
        "load": {
          "result": "executed",
          "command": "opencode debug skill",
          "commands": [
            {
              "command": "opencode debug skill",
              "exit_status": 1
            }
          ],
          "evidence": "Ran 1 command(s); exit status 1. The client reported the subcommand this stage uses as unknown. The client's output named 0 of 13 declared skill unit(s)."
        },
        "invocation": {
          "result": "blocked",
          "reason": "OpenCode installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/admission.py', 'scripts/build_loop.py', 'scripts/intent_envelope.py', 'scripts/lifecycle_state.py', 'scripts/merge_turn.py', 'scripts/parse_issue.py', 'scripts/qa_strategies.py', 'scripts/release_step.py', 'scripts/review_roster.py', 'scripts/run_record.py', 'scripts/saga.py', 'scripts/shaping_judgments.py'. A stage that half ran did not run, so invocation is blocked in advance."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "The client engaged with the package and could not fully consume it. Executed: placement, discovery, load. Blocked: invocation. Exited non-zero at: discovery, load. At discovery, the client reported the subcommand this stage uses as unknown. At load, the client reported the subcommand this stage uses as unknown. invocation: OpenCode installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/admission.py', 'scripts/build_loop.py', 'scripts/intent_envelope.py', 'scripts/lifecycle_state.py', 'scripts/merge_turn.py', 'scripts/parse_issue.py', 'scripts/qa_strategies.py', 'scripts/release_step.py', 'scripts/review_roster.py', 'scripts/run_record.py', 'scripts/saga.py', 'scripts/shaping_judgments.py'."
    },
    {
      "name": "Gemini CLI",
      "version": "0.57.0",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "gemini skills link <package>/skills/brainstorm",
          "commands": [
            {
              "command": "gemini skills link <package>/skills/brainstorm",
              "exit_status": 0
            },
            {
              "command": "gemini skills link <package>/skills/code-review",
              "exit_status": 0
            },
            {
              "command": "gemini skills link <package>/skills/doc-review",
              "exit_status": 0
            },
            {
              "command": "gemini skills link <package>/skills/founder-review",
              "exit_status": 0
            },
            {
              "command": "gemini skills link <package>/skills/ideate",
              "exit_status": 0
            },
            {
              "command": "gemini skills link <package>/skills/investigate",
              "exit_status": 0
            },
            {
              "command": "gemini skills link <package>/skills/office-hours",
              "exit_status": 0
            },
            {
              "command": "gemini skills link <package>/skills/plan",
              "exit_status": 0
            },
            {
              "command": "gemini skills link <package>/skills/qa",
              "exit_status": 0
            },
            {
              "command": "gemini skills link <package>/skills/retro",
              "exit_status": 0
            },
            {
              "command": "gemini skills link <package>/skills/spec",
              "exit_status": 0
            },
            {
              "command": "gemini skills link <package>/skills/strategy",
              "exit_status": 0
            },
            {
              "command": "gemini skills link <package>/skills/work",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 13 command(s); exit status 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0. The client's output named the package name, 13 of 13 declared skill unit(s)."
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
          "evidence": "Ran 1 command(s); exit status 0. The client's output named the package name, 13 of 13 declared skill unit(s)."
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
          "evidence": "Ran 1 command(s); exit status 0. The client's output named the package name, 13 of 13 declared skill unit(s)."
        },
        "invocation": {
          "result": "blocked",
          "reason": "Gemini CLI installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/admission.py', 'scripts/build_loop.py', 'scripts/intent_envelope.py', 'scripts/lifecycle_state.py', 'scripts/merge_turn.py', 'scripts/parse_issue.py', 'scripts/qa_strategies.py', 'scripts/release_step.py', 'scripts/review_roster.py', 'scripts/run_record.py', 'scripts/saga.py', 'scripts/shaping_judgments.py'. A stage that half ran did not run, so invocation is blocked in advance."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "The client engaged with the package and could not fully consume it. Executed: placement, discovery, load. Blocked: invocation. invocation: Gemini CLI installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/admission.py', 'scripts/build_loop.py', 'scripts/intent_envelope.py', 'scripts/lifecycle_state.py', 'scripts/merge_turn.py', 'scripts/parse_issue.py', 'scripts/qa_strategies.py', 'scripts/release_step.py', 'scripts/review_roster.py', 'scripts/run_record.py', 'scripts/saga.py', 'scripts/shaping_judgments.py'."
    },
    {
      "name": "Muse",
      "version": "1.3.0",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "muse skills install <package>/skills/brainstorm --scope user",
          "commands": [
            {
              "command": "muse skills install <package>/skills/brainstorm --scope user",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/code-review --scope user",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/doc-review --scope user",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/founder-review --scope user",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/ideate --scope user",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/investigate --scope user",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/office-hours --scope user",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/plan --scope user",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/qa --scope user",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/retro --scope user",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/spec --scope user",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/strategy --scope user",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/work --scope user",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 13 command(s); exit status 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0. The client's output named 13 of 13 declared skill unit(s)."
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
          "evidence": "Ran 1 command(s); exit status 0. The client's output named the package name, 13 of 13 declared skill unit(s)."
        },
        "load": {
          "result": "executed",
          "command": "muse skills install <package>/skills/brainstorm --scope user --force --json",
          "commands": [
            {
              "command": "muse skills install <package>/skills/brainstorm --scope user --force --json",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/code-review --scope user --force --json",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/doc-review --scope user --force --json",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/founder-review --scope user --force --json",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/ideate --scope user --force --json",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/investigate --scope user --force --json",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/office-hours --scope user --force --json",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/plan --scope user --force --json",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/qa --scope user --force --json",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/retro --scope user --force --json",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/spec --scope user --force --json",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/strategy --scope user --force --json",
              "exit_status": 0
            },
            {
              "command": "muse skills install <package>/skills/work --scope user --force --json",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 13 command(s); exit status 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0. The client's output named 13 of 13 declared skill unit(s)."
        },
        "invocation": {
          "result": "blocked",
          "reason": "Muse installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/admission.py', 'scripts/build_loop.py', 'scripts/intent_envelope.py', 'scripts/lifecycle_state.py', 'scripts/merge_turn.py', 'scripts/parse_issue.py', 'scripts/qa_strategies.py', 'scripts/release_step.py', 'scripts/review_roster.py', 'scripts/run_record.py', 'scripts/saga.py', 'scripts/shaping_judgments.py'. A stage that half ran did not run, so invocation is blocked in advance."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "The client engaged with the package and could not fully consume it. Executed: placement, discovery, load. Blocked: invocation. invocation: Muse installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/admission.py', 'scripts/build_loop.py', 'scripts/intent_envelope.py', 'scripts/lifecycle_state.py', 'scripts/merge_turn.py', 'scripts/parse_issue.py', 'scripts/qa_strategies.py', 'scripts/release_step.py', 'scripts/review_roster.py', 'scripts/run_record.py', 'scripts/saga.py', 'scripts/shaping_judgments.py'."
    },
    {
      "name": "Agy",
      "version": "1.2.7",
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
          "evidence": "Ran 1 command(s); exit status 0. The client's output named the package name, 1 of 13 declared skill unit(s)."
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
          "evidence": "Ran 1 command(s); exit status 0. The client's output named the package name, 1 of 13 declared skill unit(s)."
        },
        "load": {
          "result": "executed",
          "command": "agy plugin validate <client-home>/.gemini/config/plugins/saga",
          "commands": [
            {
              "command": "agy plugin validate <client-home>/.gemini/config/plugins/saga",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 1 command(s); exit status 0. The client's output named the package name, 1 of 13 declared skill unit(s)."
        },
        "invocation": {
          "result": "executed",
          "command": "<python> <client-home>/.gemini/config/plugins/saga/scripts/admission.py --help",
          "commands": [
            {
              "command": "<python> <client-home>/.gemini/config/plugins/saga/scripts/admission.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.gemini/config/plugins/saga/scripts/build_loop.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.gemini/config/plugins/saga/scripts/intent_envelope.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.gemini/config/plugins/saga/scripts/lifecycle_state.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.gemini/config/plugins/saga/scripts/merge_turn.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.gemini/config/plugins/saga/scripts/parse_issue.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.gemini/config/plugins/saga/scripts/qa_strategies.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.gemini/config/plugins/saga/scripts/release_step.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.gemini/config/plugins/saga/scripts/review_roster.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.gemini/config/plugins/saga/scripts/run_record.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.gemini/config/plugins/saga/scripts/saga.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.gemini/config/plugins/saga/scripts/shaping_judgments.py --help",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 12 command(s); exit status 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0. The client's output named the package name."
        }
      },
      "status": "works-directly",
      "reason": "All four stages ran through this client and every command exited 0: placement, discovery, load, and invocation of 12 declared entrypoint(s) from the path this client resolved."
    },
    {
      "name": "Hermes",
      "version": "0.21.3",
      "stages": {
        "placement": {
          "result": "executed",
          "command": "cp -R <package>/skills/brainstorm <client-home>/.hermes/skills/",
          "commands": [
            {
              "command": "cp -R <package>/skills/brainstorm <client-home>/.hermes/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/code-review <client-home>/.hermes/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/doc-review <client-home>/.hermes/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/founder-review <client-home>/.hermes/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/ideate <client-home>/.hermes/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/investigate <client-home>/.hermes/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/office-hours <client-home>/.hermes/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/plan <client-home>/.hermes/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/qa <client-home>/.hermes/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/retro <client-home>/.hermes/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/spec <client-home>/.hermes/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/strategy <client-home>/.hermes/skills/",
              "exit_status": 0
            },
            {
              "command": "cp -R <package>/skills/work <client-home>/.hermes/skills/",
              "exit_status": 0
            }
          ],
          "evidence": "Ran 13 command(s); exit status 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0. The command produced no output, so its exit status is the whole result."
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
          "evidence": "Ran 1 command(s); exit status 0. The client's output named 13 of 13 declared skill unit(s)."
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
          "evidence": "Ran 1 command(s); exit status 0. The client's output named the package name, 13 of 13 declared skill unit(s)."
        },
        "invocation": {
          "result": "blocked",
          "reason": "Hermes installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/admission.py', 'scripts/build_loop.py', 'scripts/intent_envelope.py', 'scripts/lifecycle_state.py', 'scripts/merge_turn.py', 'scripts/parse_issue.py', 'scripts/qa_strategies.py', 'scripts/release_step.py', 'scripts/review_roster.py', 'scripts/run_record.py', 'scripts/saga.py', 'scripts/shaping_judgments.py'. A stage that half ran did not run, so invocation is blocked in advance."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "The client engaged with the package and could not fully consume it. Executed: placement, discovery, load. Blocked: invocation. invocation: Hermes installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/admission.py', 'scripts/build_loop.py', 'scripts/intent_envelope.py', 'scripts/lifecycle_state.py', 'scripts/merge_turn.py', 'scripts/parse_issue.py', 'scripts/qa_strategies.py', 'scripts/release_step.py', 'scripts/review_roster.py', 'scripts/run_record.py', 'scripts/saga.py', 'scripts/shaping_judgments.py'."
    }
  ]
}
```
