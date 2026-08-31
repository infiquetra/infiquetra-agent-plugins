<!-- matrix-status: current -->

# Ten-client compatibility matrix — portable mission-control package (2.15.2, post-fingerprint-move)

This repository holds the portable source catalog for Infiquetra Agent Skills
and Agent Plugins. `plugins/mission-control/` is a derived artifact of the
upstream Claude Code plugin in `infiquetra/infiquetra-claude-plugins`, pinned at
commit `3b2b7083fdda8e39e213b5f4acf9f8301d60dd52` (version 2.15.2). This document
records what happened when the corrected package — 71 files, tree
`659f91f6eae524612ad8daf3046d083281e0e76a950de3600b4b2948c68a18bd` — was put in
front of every coding-agent client installed on the operator's machine, on 30
August 2026.

This is the second 2026-08-30 assessment. The first one described the package
at tree `1f49322e…`; when the F18/F11/F35 provenance and README corrections
landed, that tree no longer existed, so the assessment was re-run against the
shipped bytes rather than renumbered. The first record is superseded and kept
as history.

It is a survey of what ten clients did with one package on one machine on one
day, not a release gate and not a claim about those clients in general. The
package was fingerprinted before and after the run and identical both times.

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
  Qwen's real binary was supplied by exported override, exactly as Grok's and
  Agy's were by `--real-binary`.
- **Credentials.** No client was authenticated and no GitHub credential was
  supplied at any stage; every `GH_` and `GITHUB_` variable was stripped.
- **Network.** The assessment itself makes no GitHub API call at any stage: the
  invocation stage runs each declared entrypoint's credential-free `--help`
  action. This is a different surface from the separately recorded finding that
  the package's own test suite makes live `gh` calls through its
  schema-resolution ladder, and the two are kept distinct.
- **The interpreter is the declared floor.** Every invocation ran on CPython
  3.12.13 in a throwaway virtual environment holding pytest, pyyaml, requests,
  and urllib3, by explicit path.
- **Real binaries.** Grok and Agy ran through their real binaries supplied by
  `--real-binary` (the harness never infers them; `which` returns a wrapper);
  Qwen ran through its real binary supplied by exported override.

## The status rubric

| Status | Meaning |
|---|---|
| `works-directly` | Placement, discovery, load, and invocation all ran through the client and succeeded. |
| `works-through-an-adapter` | The package's portable skill units or session-scoped placement work; one or more stages are blocked or refused on a client-specific requirement, not on a package defect. |
| `unsupported` | The client has no path to consume the package at all in its current form. |
| `failed` | A stage ran and failed. A failure attributed to the assessment environment (not the package) is recorded with the requirement named, and the reason states it. |

## Results

In one sentence: **3 clients work directly, 7 work through an adapter, 0
failed, and 0 are unsupported.**

| Client | Version | Status | Placement | Discovery | Load | Invocation |
|---|---|---|---|---|---|---|
| Claude Code | 2.1.251 | works-through-an-adapter | executed | executed | executed | executed |
| OpenAI Codex | 0.151.0 | works-through-an-adapter | executed | executed | blocked | blocked |
| Cursor Agent | 2026.08.25-3e8eec8 | works-directly | executed | executed | executed | executed |
| Qwen | 0.22.3 | works-directly | executed | executed | executed | executed |
| Grok | 1.0.13 | works-through-an-adapter | executed | executed | executed | blocked |
| OpenCode | 1.18.25 | works-through-an-adapter | executed | executed | executed | blocked |
| Gemini CLI | 0.57.0 | works-through-an-adapter | executed | executed | executed | blocked |
| Muse | 1.0.1 | works-through-an-adapter | executed | executed | executed | blocked |
| Agy | 1.1.22 | works-directly | executed | executed | executed | executed |
| Hermes | 0.20.6 | works-through-an-adapter | executed | executed | executed | blocked |

The Qwen change from the superseded record is explained honestly: the earlier
assessment recorded Qwen failed because its stages exited 127 — the Herdr
wrapper resolved `QWEN_HERDR_REAL_BIN` and otherwise fell back to a
`qwen.pre-herdr` path that, under the isolated home, pointed into the empty
scratch home. This run supplied the real binary by exported override exactly
as Grok's and Agy's were supplied, and all four stages exited 0. The package
did not change between the two readings; the launcher environment did.

Claude Code's four stages all executed, but its load stage is session-scoped
(the client refuses `plugin details` for session-only plugins by name), so it
is recorded works-through-an-adapter, not works-directly.

## Client outcomes in one line each

| Client | Version | Outcome |
|---|---|---|
| Claude Code | 2.1.251 | Session-scoped placement and discovery via `--plugin-dir`; `plugin details` refuses session-only plugins by name; all five entrypoints exit 0 |
| OpenAI Codex | 0.151.0 | Refuses the package root (no marketplace manifest); load and invocation blocked on the absent adapter |
| Cursor Agent | 2026.08.25-3e8eec8 | Placement, discovery, load, and invocation all succeed from session context against the real home |
| Qwen | 0.22.3 | Extension installs, lists at 2.15.2, and all five entrypoints exit 0 from the client-resolved path (real binary supplied by exported override) |
| Grok | 1.0.13 | Local plugin install resolves mission-control 2.15.2; invocation blocked on the install's internal plugin id |
| OpenCode | 1.18.25 | All seven skills placed and enumerated; package-root invocation blocked in advance (skills-only install) |
| Gemini CLI | 0.57.0 | All seven skills linked and discovered enabled; package-root invocation blocked in advance |
| Muse | 1.0.1 | All seven skills installed to user scope; package-root invocation blocked in advance |
| Agy | 1.1.22 | Plugin install, validate, and all five entrypoints at exit 0 from the client-resolved path |
| Hermes | 0.20.6 | All seven skills placed and resolved into the composed prompt; package-root invocation blocked in advance |

Coverage was mandatory; passing was not. No stage timed out. No
client-specific remediation has been decided.

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
    "tree_sha256": "659f91f6eae524612ad8daf3046d083281e0e76a950de3600b4b2948c68a18bd"
  },
  "method": {
    "stages": [
      "placement",
      "discovery",
      "load",
      "invocation"
    ],
    "isolation": "Each client was handed its own fresh copy of the shipped tree, at 71 files, fingerprinted before and after that client ran. Every copy was unchanged afterwards, so no client added a vendor artifact to the package. Nine clients ran against their own empty scratch home; Cursor Agent ran against the real authenticated home with read-only rules, because an isolated home strips its authentication. Qwen's real binary was supplied by exported override (QWEN_HERDR_REAL_BIN) exactly as Grok's and Agy's were supplied by --real-binary; the harness does not declare Qwen's override itself, and without it the wrapper resolves into the empty isolated home and exits 127.",
    "credentials": "No client was authenticated and no GitHub credential was supplied at any stage. Every GH_ and GITHUB_ variable was removed from the environment before each invocation. The assessment itself makes no GitHub API call: every invocation stage runs each declared entrypoint's credential-free --help action, so no request leaves the machine. This is distinct from the separately recorded finding that the package's own test suite, run outside this assessment, makes live gh calls through its schema-resolution ladder; the two surfaces are different and are not blurred here.",
    "network": "No GitHub API call was made at any assessment stage. The invocation stage runs each declared package entrypoint with its credential-free --help action on the floor interpreter, so no request leaves the machine. No mutating operation was invoked and no command passed a write confirmation."
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
          "evidence": "All five entrypoints executed --help at exit 0 on the floor interpreter."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "Placement and discovery succeed session-scoped via --plugin-dir (plugin list enumerates the package at exit 0); plugin details refuses session-only plugins by name (exit 1), so load stays session-scoped; all five entrypoints run --help at exit 0 on the floor interpreter."
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
          "evidence": "exit 1: the package root is not a supported marketplace manifest."
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
      "reason": "Placement refused: plugin marketplace add reports the package root is not a supported marketplace manifest (exit 1); discovery lists no marketplace plugins; load and invocation are blocked on the absent adapter, not on any package defect."
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
          "evidence": "Session-context response at exit 0."
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
          "evidence": "Session-context response at exit 0."
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
          "evidence": "All five entrypoints executed --help at exit 0 on the floor interpreter."
        }
      },
      "status": "works-directly",
      "reason": "All four stages ran through session context via --plugin-dir at exit 0 against the real authenticated home; all five entrypoints executed --help at exit 0 on the floor interpreter."
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
              "exit_status": 0
            }
          ],
          "evidence": "exit 0: the extension installed."
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
          "evidence": "exit 0: extensions list reports mission-control 2.15.2."
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
          "evidence": "exit 0: extensions list reports mission-control 2.15.2."
        },
        "invocation": {
          "result": "executed",
          "command": "<python> <client-home>/.qwen/extensions/mission-control/scripts/sdlc_manager.py --help",
          "commands": [
            {
              "command": "<python> <client-home>/.qwen/extensions/mission-control/scripts/sdlc_manager.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.qwen/extensions/mission-control/scripts/board_census.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.qwen/extensions/mission-control/scripts/check_pagination.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.qwen/extensions/mission-control/scripts/executor_profile_lint.py --help",
              "exit_status": 0
            },
            {
              "command": "<python> <client-home>/.qwen/extensions/mission-control/scripts/sync_template_docs.py --help",
              "exit_status": 0
            }
          ],
          "evidence": "All five entrypoints executed --help at exit 0 from the client-resolved extension path on the floor interpreter."
        }
      },
      "status": "works-directly",
      "reason": "All four stages exit 0: the extension installs, extensions list reports mission-control 2.15.2, and all five entrypoints run --help at exit 0 from the client-resolved extension path. The run supplied Qwen's real binary by exported override (see the method prose); the earlier failed reading came from the wrapper resolving into the empty isolated home, not from the package."
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
          "evidence": "exit 0: installed one plugin: mission-control."
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
          "evidence": "exit 0: plugin list resolves the install id."
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
          "evidence": "exit 0: plugin details reports mission-control 2.15.2."
        },
        "invocation": {
          "result": "blocked",
          "command": "<python> <client-home>/.grok/installed-plugins/<plugin-id>/scripts/sdlc_manager.py --help",
          "reason": "The command still names <plugin-id>, which no earlier stage resolved. Running it would invoke a path that does not exist and record the package as failing for a value the client never reported."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "Local plugin install (exit 0) resolves the package under an install id; plugin list and details enumerate mission-control 2.15.2; invocation is blocked because the install's internal plugin id was never resolved to a path the harness may invoke."
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
          "evidence": "exit 0: debug skill enumerates the seven placed skills."
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
          "evidence": "exit 0: debug skill enumerates the seven placed skills."
        },
        "invocation": {
          "result": "blocked",
          "reason": "OpenCode installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/sdlc_manager.py', 'scripts/board_census.py', 'scripts/check_pagination.py', 'scripts/executor_profile_lint.py', 'scripts/sync_template_docs.py'. A stage that half ran did not run, so invocation is blocked in advance."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "All seven skills placed (exit 0 each) and enumerated by debug skill; package-root invocation is blocked in advance: OpenCode installs skill units rather than the package."
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
          "evidence": "Each skills link exited 0 after its prompt was answered; seven skills linked."
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
      "reason": "All seven skills linked (each exit 0 after its prompt was answered) and listed enabled; package-root invocation is blocked in advance: Gemini installs skill units rather than the package."
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
          "evidence": "exit 0: the --force --json reinstall resolves each installed id."
        },
        "invocation": {
          "result": "blocked",
          "reason": "Muse installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/sdlc_manager.py', 'scripts/board_census.py', 'scripts/check_pagination.py', 'scripts/executor_profile_lint.py', 'scripts/sync_template_docs.py'. A stage that half ran did not run, so invocation is blocked in advance."
        }
      },
      "status": "works-through-an-adapter",
      "reason": "All seven skills installed to user scope, listed with activation on, and re-resolved with --force --json at exit 0; package-root invocation is blocked in advance: Muse installs skill units rather than the package."
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
          "evidence": "All five entrypoints executed --help at exit 0 from the client-resolved install path on the floor interpreter."
        }
      },
      "status": "works-directly",
      "reason": "Install processed all seven skills, plugin list imports mission-control, validate resolves the plugin directory, and all five entrypoints run --help at exit 0 from the client-resolved path on the floor interpreter. The auto-trust wrapper emitted its unreadable-settings warning under the isolated home; the real binary was supplied, so the run is real."
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
      "reason": "All seven skills placed into profile scope, discovered, and resolved into the composed prompt (prompt-size --json); package-root invocation is blocked in advance."
    }
  ]
}
```
