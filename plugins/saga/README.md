# saga

Saga is the portable lifecycle package for turning an unframed ask into a
reviewed plan, a build, a review, evidence, and a record of what was learned.
The portable core is the skills and the scripts at this package root. Claude
Code commands and hooks live under `com.infiquetra.claude/` and are not part
of the portable core.

Version 1.2.1 is the authored cut of upstream 1.2.0. This repository maintains
the package from here on. There is no provenance manifest.

## Layout

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Portable Agent Plugins manifest. Name, version, description. No behaviour. |
| [`skills/`](skills/) | One skill per lifecycle capability. Open Agent Skills frontmatter. |
| [`scripts/`](scripts/) | The lifecycle engine: run record, admission, plan checks, review, QA, release. |
| [`references/`](references/) | Contracts the skills and scripts share (run record, QA catalogue, plan-save). |
| [`scripts/_bundled/`](scripts/_bundled/) | Build-time copy of the Fleet Core modules this package loads. Generated. Do not edit. |
| [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) | Claude packaging manifest. Paths only, into the adapter and into `skills/`. |
| [`com.infiquetra.claude/commands/`](com.infiquetra.claude/commands/) | Claude slash commands. Fourteen files, thirteen capabilities. `/ceo-review` is an alias for `/founder-review`. |
| [`com.infiquetra.claude/hooks/`](com.infiquetra.claude/hooks/) | Claude hooks: SessionStart, UserPromptSubmit, PreCompact, PreToolUse, PostToolUse. |

## How a harness reaches it

Skill-scoped harnesses (OpenCode, Gemini CLI, Muse, Hermes) install a directory
under `skills/<name>/`. Each `SKILL.md` says which script to run and which
environment variables that script reads. The script path inside a catalog
checkout is `plugins/saga/scripts/<script>.py`. After a Claude install the same
files are at the package root, and `CLAUDE_PLUGIN_ROOT` names that root.

Claude Code installs this package from the repository marketplace. The root
manifest points `commands` and `hooks` at `com.infiquetra.claude/` and `skills`
at `skills/`. Restart Claude Code after installing so the hooks register.

Run a script directly, with no credentials, to see its flags:

```bash
python3 plugins/saga/scripts/saga.py --help
python3 plugins/saga/scripts/admission.py --help
```

`typesafe-sdk` is imported only when a script actually calls the TypeSafe
service. `--help` does not need it. `TYPESAFE_API_KEY` is the credential name
when a call is made. A missing key fails open on the advisory judgments.

The lifecycle checkout, when a script needs it, is `INFIQUETRA_SDLC_PATH`,
then `INFIQUETRA_SDLC_ROOT`, then `~/workspace/infiquetra/infiquetra-sdlc`.

## Lifecycle

The main chain, named as skills. Claude shows the same names as slash commands.

```text
idea/requirements-ready -> plan -> doc-review -> work -> code-review -> qa -> retro
```

Off the chain, and still first-class: `spec` sharpens WHAT, `investigate`
diagnoses a root cause, `strategy` records direction, `founder-review` reviews
scope. `office-hours`, `ideate`, and `brainstorm` come before planning.

| Situation | Skill | Next artifact |
|---|---|---|
| The ask is still unframed | `office-hours` | frame note and route |
| You want grounded options | `ideate` | `docs/ideation/` |
| One idea needs requirements | `brainstorm` | `docs/brainstorms/` |
| The WHAT is vague | `spec` | `docs/specs/` |
| The WHAT is settled and needs HOW | `plan` | `docs/plans/` |
| A plan needs readiness review | `doc-review` | `docs/reviews/` |
| A reviewed plan should be built | `work` | `docs/work-sessions/`, pull request |
| A built branch needs review | `code-review` | `docs/code-reviews/` |
| Merged work needs evidence | `qa` | `docs/qa/` |
| A defect needs a root cause | `investigate` | debug report |
| Finished work should teach the lifecycle | `retro` | journal or retro artifact |

Destination sets how far a run goes: `plan-only`, `pr`, `merge`, or
`nonprod-deploy`. Deployment mutation belongs to the deploy package.
Issue and board mutation belongs to mission-control. Saga submits those moves.
It does not call GitHub's project fields itself.

## State

Saga stores `lifecycle_phase`, `phase_status`, and `status` in local,
git-ignored saga ticks. `maturity` is derived at handoff time and is not stored
as saga state. The run record is one JSON file per issue, written by
`scripts/run_record.py`. The contract is [references/run-record.md](references/run-record.md).

## Tests

```bash
python3 -m pytest plugins/saga/tests -q
```

The manual pages under [docs/](docs/) are the longer reference: lifecycle,
command selection, state and readiness, scenarios, and ownership boundaries.
