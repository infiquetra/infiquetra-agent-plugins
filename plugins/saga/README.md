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
| [`com.infiquetra.claude/commands/`](com.infiquetra.claude/commands/) | Claude slash commands. 15 files and 14 commands. `/ceo-review` is an alias for `/founder-review`. |
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

In Claude Code, `/plan-view` reads the run's plan one section at a time in a
pane. Every other harness reads the plan file itself; `python3
plugins/saga/scripts/run_status.py summary` prints its path.

In Claude Code, `/setup-view` opens the setup pane directly — the survey, the
installs, and the optional steps with no agent turn. Every other harness uses
`/saga:setup`.

## Review tool execution

The review-tool runner gives each POSIX invocation its own session/process group.
Before returning or releasing temporary tool directories, it sends the group TERM,
allows up to half a second for shutdown, then sends KILL and reaps the direct
process. This also covers background children left by a normally exiting parent
and Python cancellation such as `KeyboardInterrupt`. The synchronous `prepare`
CLI unwinds cleanup on SIGTERM and exits 143; callers must allow the nested
half-second group grace plus temporary-directory cleanup before escalating.
Imported API callers own their cancellation policy. Deliberately detached
descendants and a runner killed with SIGKILL remain outside this boundary. On
other platforms, cleanup controls only the direct subprocess. This is a process
lifetime boundary, not a sandbox.

`review_command.py prepare --diagnostics-directory <private-directory>` and
`review_tools.py run --diagnostics-directory <private-directory>` optionally retain
local cargo-mutants attempt diagnostics. The Python runner accepts the same
`diagnostics_directory` keyword, defaulting to `None`. Each initial/retry attempt
gets a separate directory and typed `attempt.json` (`review_diagnostics.v1`) with
status, reason, exit code, elapsed time, starting remaining budget, and artifact
references. Failed and budget-skipped retries remain visible without replacing the
original review outcome. Console text, the outcomes report, and referenced baseline
logs are bounded to eight files and 256 KiB total per attempt (64 KiB per artifact).
Small text stays byte-exact. Larger console and baseline text retains its beginning
and ending around an explicit omission separator, counted within the same cap.
Artifact metadata records the sample mode, observed/original byte size and omitted
byte span. A small remaining budget retains only the tail, or no text when exhausted.
Baseline sampling uses bounded reads and seeks on the same safely opened descriptor;
if the source changes during capture, metadata marks it incomplete and leaves the
original size and omitted offsets unknown. The outcomes JSON keeps prefix capture
and its existing parsing behavior.
Directories are mode 0700 and files 0600. Log reads refuse symlinks, paths outside
the scan root, nonregular files, and platforms without safe descriptor traversal.
Capture failures are noted locally and preserve the scan outcome. Diagnostics can
contain reviewed source or test output: keep them private, outside the packet
directory. They never enter packet records, raw-output digests, grades, or hashes.

## Tests

```bash
python3 -m pytest plugins/saga/tests -q
```

The manual pages under [docs/](docs/) are the longer reference: lifecycle,
command selection, state and readiness, scenarios, and ownership boundaries.
