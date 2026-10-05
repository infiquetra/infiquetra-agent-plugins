---
title: saga: /saga:setup checks and prepares the machine and the repository
repo: infiquetra-agent-plugins
type: enhancement
team: asgard
project: operations
labels: enhancement, needs-plan
risk: medium
handoff_maturity: requirements-ready
stage: Shaping
status: Discovering
approval_state: approved
---

# saga: /saga:setup checks and prepares the machine and the repository

### Objective

Saga gains a setup step of its own, `/saga:setup`, run by one vendor-neutral script that any harness can call. It shows which tools saga needs are installed, missing or at the wrong version, checks that the sandbox for reproduction tests is available, installs only the tools the operator names and runs optional machine steps only on approval. It records the machine's result in a machine record in the user's home directory, and the repository's languages, visibility, pinned review tools, functional-test environment and `/qa` strategies in `.saga-profile.json`. A run never asks setup questions: it reports missing tools once, naming them and `/saga:setup`, and admission asks only for what setup has not recorded.

### Intent

This card implements plan.md, Change 2 ("A saga setup step for tools"), except its screens.

What is true on origin/main today:

- Saga has no setup or tool-detection step. The old `/fleet-doctor` command was removed, and the command surface test keeps it removed (`plugins/saga/tests/test_command_surface.py:44-69`). No saga script looks for an installed program or detects a repository's languages.
- The command surface is pinned at 14 command files (13 commands plus the `/ceo-review` alias) and 13 skill directories (`test_command_surface.py:24-39`, `:79-104`). `plugins/saga/docs/commands.md:3` and `plugins/saga/README.md:22` state the same counts.
- The repository profile (`plugins/saga/references/repository-profile.md`, schema token `repository_profile.v1`) holds the mechanical baseline, preflight checks, the functional-test environment or its waiver, and an optional `qa` block (`plugins/saga/references/qa-profile.schema.json`). It records no languages, visibility or tool versions. The build loop's reference notes that scoping a scanner to the change needs "a profile field repository_profile.v1 does not have" (`plugins/saga/references/mechanical-baseline.md:93-95`).
- Admission (`plugins/saga/scripts/admission.py`) never prompts. It prints the questions left and reads an answers file (`admission.py:18-21`). It reads other repository facts from the profile (`admission.py:84-94`), drops the functional-test question when the profile answers it (`admission.py:346-360`), and writes an answer back through `write_declaration` (`plugins/saga/scripts/functional_environment.py:308-341`).
- `/qa` refuses a repository with no `qa` block (`qa-profile.schema.json` description; `plugins/saga/scripts/qa_strategies.py:80`).
- In infiquetra-sdlc, the saga adapter (`tools/docs/saga_adapter.py`) refuses to resolve a command missing from `saga_lifecycle.command_classification`.

What changes:

1. A `/saga:setup` command in the Claude adapter and a `setup` skill at the package root, both running one new script. In harnesses without mods the skill prints the survey as a table and asks numbered questions.
2. Setup reads the default tool list, which holds plan.md's "Default tools" table with each tool's lens, default version, rule set, version check and install command. This card adds rows for the command-line tools saga itself uses (git; GitHub's `gh`, signed in; Python at the catalog's 3.12 floor; uv; PyYAML). C6 adds the row for the parser the sweep needs outside Python, and setup checks it like any other row.
3. The machine survey. For saga's own tools and the review tools of the detected languages, it reports installed, missing, or at a version other than the pin. It reports whether `TYPESAFE_API_KEY`, `SAGA_LANGFUSE_PUBLIC_KEY`, `SAGA_LANGFUSE_SECRET_KEY` and `SAGA_LANGFUSE_HOST` are set, without ever printing a value. It checks that the sandbox for reproduction tests is available (write access to the scratch copy only, no network, no credentials); without it, reproduction is unavailable and a run is degraded. It prints a table, and a machine-readable form for C14's setup pane.
4. The machine record. Setup records what it found (each tool's status and version, the sandbox check, which optional steps are done), that it ran, and whether setup has been offered, in a record in the user's home directory, outside any repository. The Claude Code mod's first-session offer (C14) writes the same "offered" fact there as well as in its own store.
5. Installing and optional steps, on approval only. The script installs only the tools the operator names and shows each install's progress as it runs. It also lists optional machine steps that other cards add, shows whether each is done, and runs one only when the operator names it; C16 adds installing the daily outcome job's schedule. The survey itself is read-only.
6. The repository survey writes `.saga-profile.json`. It records the detected languages (Python including Cloud Development Kit (CDK) code, TypeScript, Dart, Rust, Swift, Markdown, shell scripts and GitHub workflows), the repository's visibility (public or private; C15 posts a private repository's reviews only to an `https` Langfuse host), and each tool's pinned version and rule set in the profile block C4a defines. It writes the functional-test environment through `write_declaration`, so admission reads it as it does today, and the `qa` block, valid against `qa-profile.schema.json`. Like admission, the script emits questions and consumes answers. Every other key keeps its value and place, and the write is atomic.
7. During a run, saga checks the pinned tools and the sandbox once, at admission, and asks nothing. It records one notice on the run record naming each missing tool, or the missing sandbox, and `/saga:setup`. `plugins/saga/scripts/run_status.py` prints the notice in the run status. C13 shows it in the review summary and the pull request comment, and C14 in the status line.
8. Admission asks only for what a run needs that setup has not recorded, and keeps reading the other repository facts from the profile as today; setup does not ask them. On a machine where setup has never run and never been offered, saga's first run prints one line suggesting `/saga:setup` and records the offer in the machine record, so the line appears once (plan.md: "Other harnesses print a one-line suggestion on saga's first run"). This card owns that line for harnesses without mods.
9. The command surface pins move deliberately to 15 files, 14 commands and 14 skill directories, and the documents that state the counts move with them.

Depends on X1a (Record saga's new review model and its contracts in the lifecycle repository), which classifies `/saga:setup` in `saga_lifecycle.command_classification` so the lifecycle repository's saga adapter resolves it, and on C4a (saga: build-loop tool framework reporting only what a change introduces). Setup reads and extends the default tool list, and writes the profile block of pinned versions, that C4a (saga: build-loop tool framework reporting only what a change introduces) defines; C4b and C4c add their languages' rows. C6 (fleet-core + saga: the Jev sweep says where to look in a change) adds its parser's row. C5 (saga: pattern checks for the defects we keep hitting) adds the repository question for shared update paths. C14 (saga mods: review pane, merge confirmation, run band and setup pane) renders the survey and passes the operator's ticked tools to this card's script. C15 reads the visibility and the Langfuse variables, and C16 adds the outcome job's step.

### Risk

medium
It adds a command to a surface pinned by tests and writes the tracked profile and a record in the user's home, but it installs nothing and runs no step the operator did not name, and never prints a key.

### Out-of-scope / non-goals

- The Claude Code setup pane, the first-session offer and the status-line entry for missing tools: C14.
- Running the review tools and turning their output into records: C4a, C4b (saga: review tools for Python, CDK, shell, workflows and Markdown) and C4c (saga: review tools for TypeScript, Dart, Rust and Swift).
- Which lenses may block when a profile pins other versions: C2 (saga: the calibration file decides which lenses may block).
- Showing the notice in the review summary and the pull request comment: C13 (saga: review state for every harness, the pull request checklist and fix-later choices).
- Choosing the sweep's parser: C6's planning step. Creating the Langfuse project and keys, and posting by visibility: C15 (fleet-core + saga: Langfuse review traces and outcomes at merge).
- The outcome job and its schedule step: C16 (saga: tie /qa and later defects back to the review that passed the code); this card provides the optional-step mechanism.
- The sandbox itself and running reproduction tests in it: C8 (saga + agent-launcher: the targeted LLM reviewer) and C10a (saga: one review command from change to records); this card only checks that it is available.
- The question for the repository's shared update paths: C5 (saga: pattern checks for the defects we keep hitting).
- Removing admission's lens-declaration and round-allowance questions: C10b (saga: switch /code-review to the review command, with the new round and merge rules).
- The pinned tools as a required CI check: X2. This repository's own profile: issue #114.
- Running setup inside a run or the build loop: the plan rules it out.

### Files expected to change

- `plugins/saga/scripts/saga_setup.py` (new)
- `plugins/saga/com.infiquetra.claude/commands/setup.md` (new)
- `plugins/saga/skills/setup/SKILL.md` (new)
- `plugins/saga/references/review-tools.yaml` (rows for saga's own tools)
- `plugins/saga/references/repository-profile.md`
- `plugins/saga/references/run-record.md`
- `plugins/saga/scripts/admission.py`
- `plugins/saga/scripts/run_status.py`
- `plugins/saga/docs/commands.md`
- `plugins/saga/README.md`
- `plugins/saga/CHANGELOG.md`
- `docs/engineering-journal/DECISIONS.md`
- `plugins/saga/tests/test_saga_setup.py` (new)
- `plugins/saga/tests/test_command_surface.py`
- `plugins/saga/tests/test_admission.py`
- `plugins/saga/tests/test_run_status.py`
- `plugins/saga/tests/test_entrypoints.py`

### Tests to add or update

- `plugins/saga/tests/test_saga_setup.py` (new). It uses an injected runner, environment and home directory, makes no network call and installs nothing. It asserts that:
  - on a fixture repository with Python, TypeScript and shell files, the survey reports installed, missing and wrong-version tools for those languages only;
  - with `TYPESAFE_API_KEY` and the three `SAGA_LANGFUSE_` variables set to sentinel values, both output forms say "present" and never contain a sentinel;
  - with the sandbox probe failing, the survey reports reproduction as unavailable;
  - the survey calls no install command and runs no optional step; an install calls exactly the named tools' install commands, and a fixture optional step reports done or not done and runs only when named;
  - the machine record lands under the injected home directory, never inside the repository, and holds the survey result, the run and the offer;
  - the profile write keeps every other key and its order, records languages and visibility, creates the file with `"schema": "repository_profile.v1"` when absent, and is atomic;
  - the functional-test answer lands through `write_declaration`, and the `qa` block validates against `qa-profile.schema.json`;
  - the run's notice is recorded once, names each missing tool or the missing sandbox and `/saga:setup`, and asks no question.
- `plugins/saga/tests/test_command_surface.py`: 15 files, `setup` among the surviving commands, 14 skill directories, and the `setup` skill resolved by its command.
- `plugins/saga/tests/test_admission.py`: a profile written by setup leaves no functional-test question, and the other profile facts are read as today; the suggestion line appears on the first run when setup has never run or been offered, records the offer, and does not appear again.
- `plugins/saga/tests/test_run_status.py`: the summary carries the notice as an additive key inside `run_status.v1`.
- `plugins/saga/tests/test_entrypoints.py`: discovers the new script's `--help`; add `SAGA_LANGFUSE_` to `CREDENTIAL_PREFIXES`.

### Context library links

- infiquetra-context-library `docs/delivery/ci-cd-standards.md` and `docs/testing/quality-gates.md` (the standard X2 extends)
- infiquetra-context-library `docs/repositories/python-toolchain.md` ("Toolchain Version Pins")
- infiquetra-context-library `docs/security/data-and-secrets.md`
- `plugins/saga/references/repository-profile.md` and `plugins/saga/references/qa-profile.schema.json`
- `docs/engineering-journal/DECISIONS.md`, 2026-10-04: "A repository's functional-test environment lives in its tracked saga profile, and admission writes it once"

### Acceptance criteria

- [ ] `ls plugins/saga/com.infiquetra.claude/commands | wc -l` prints 15, and `python3 -m pytest plugins/saga/tests/test_command_surface.py -q --import-mode=importlib` passes.
- [ ] `python3 plugins/saga/scripts/saga_setup.py --help` exits 0 with no credentials in the environment.
- [ ] The survey lists every saga tool and every review tool for the detected languages, with its status, the lens it serves and its pinned version, as a table and in machine-readable form.
- [ ] The survey reports `TYPESAFE_API_KEY`, `SAGA_LANGFUSE_PUBLIC_KEY`, `SAGA_LANGFUSE_SECRET_KEY` and `SAGA_LANGFUSE_HOST` only as present or absent, and a test proves a sentinel value never reaches standard output or standard error.
- [ ] The survey reports whether the reproduction sandbox is available; without it, the run's notice names it and reproduction is marked unavailable.
- [ ] Nothing is installed, and no optional machine step runs, unless the operator named it.
- [ ] The machine record sits in the user's home directory, outside any repository, and holds the survey result, that setup ran and that it was offered.
- [ ] Setup writes the languages, visibility, pins, functional-test environment and `qa` block into `.saga-profile.json` and keeps every other key; `repository-profile.md` describes the new keys and setup as a writer of the profile.
- [ ] A run asks no setup question, and the missing-tool notice appears once per run in `run_status.py summary` and on the run record.
- [ ] Admission asks for nothing setup recorded, reads the other profile facts as today, and prints the `/saga:setup` suggestion once per machine when setup has never run or been offered.
- [ ] `plugins/saga/docs/commands.md` has a card for `/saga:setup`, and the counts there and in `plugins/saga/README.md` read 15 files and 14 commands.
- [ ] `python3 scripts/check_repo.py` passes, including its frontmatter check of the new skill.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 plugins/saga/scripts/saga_setup.py --help
ls plugins/saga/com.infiquetra.claude/commands | wc -l
```

### Notes / conventions

- For the planning step: the machine record's path and format under the home directory, and where the format is documented (the setup skill or a reference beside it). It stays separate from the per-repository run store, `.claude/saga/runs` (`plugins/saga/scripts/run_record.py:74`).
- For the planning step: how a card registers an optional machine step (its name, what it does, how to tell it is done, how to run it) or a repository question (its profile key and wording), so C16 adds its step and C5 its question without changing the script's flow.
- For the planning step: the sandbox probe runs a trivial command through the mechanism C8's and C10a's planning steps pick for reproduction tests.
- For the planning step: the profile key names for languages and visibility, and how visibility is read (for example `gh repo view --json visibility`). The standard `LANGFUSE_*` variables hold the tracing plugin's keys, so setup checks only the `SAGA_LANGFUSE_*` names; the TypeSafe name matches `plugins/fleet-core/scripts/fleet_commons/typesafe_client.py:93`.
- For the planning step: this card adds no root `.saga-profile.json`. Adding one (issue #114) switches on the live-profile tests at `plugins/saga/tests/test_admission.py:24` and `:314`.

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-05-saga-review-redesign/cards/C3-saga-setup.md

### Source context
- Source: docs/brainstorms/2026-10-05-saga-review-redesign/cards/C3-saga-setup.md
- Source type: brainstorm
- Source title: saga: /saga:setup checks and prepares the machine and the repository

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/150
- Number: 150
- Created at: 2026-10-05T19:09:28.063408+00:00
