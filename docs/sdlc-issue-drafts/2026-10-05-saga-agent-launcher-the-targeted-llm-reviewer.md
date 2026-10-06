---
title: saga + agent-launcher: the targeted LLM reviewer
repo: infiquetra-agent-plugins
type: enhancement
team: asgard
project: operations
labels: enhancement, needs-plan
risk: high
handoff_maturity: requirements-ready
stage: Shaping
status: Discovering
approval_state: approved
---

# saga + agent-launcher: the targeted LLM reviewer

### Objective

One LLM (large language model) reviewer, with its prompt and answer schema in saga, runs with its
normal configuration on any vendor agent-launcher staffs, started through agent-launcher the same way
in saga's reviews and in the corpus harness. It answers each where-to-look item with a finding or a
reason to clear it, tries to reproduce findings with a test in a sandboxed scratch copy, and runs one
capped open search. Code checks it skipped no item.

### Intent

Today (origin/main 1f7137d), one lens-reviewer session per selected lens runs agent-launcher's
`roles/lens-reviewer.md`, cut per lens (`roster.py:312-347`, `395-440`). It scores dimensions, is
read-only (`lens-reviewer.md:18-33`), labels severity and reproduces nothing; Jev (TypeSafe's
classifier) picks no consequence. Sessions are interactive panes that load the operator's CLAUDE.md,
plugins, hooks and MCP (Model Context Protocol) servers. The roles library is pinned to the lifecycle
repository (infiquetra-sdlc) at e5a2be10; `test_roles_library.py:590-603` requires exactly its roles.

What changes (plan.md: Change 6; "Judged findings"; the 5 October decisions, "How the reviewer runs"):

- **Prompt and schema in saga,** fingerprinted by C2 with the reviewer's vendor and model.
  Agent-launcher's new targeted-reviewer role is a thin wrapper naming saga's prompt.
- **Normal configuration, any staffed vendor:** the reviewer loads its instruction files (CLAUDE.md,
  AGENTS.md), plugins and hooks, as real reviews always will, on the subscription sign-in.
  Agent-launcher starts the role on its staffed vendor (for Claude, `claude -p`); orchestrate
  (C9) and the harness (K3) call that launch, and saga never starts it. It returns the session's
  usage and the reviewer's vendor, model and configuration fingerprint (of those files and plugins).
  Saga's agent-type list (`scripts/role_agent_types.py`) gives the role no in-session subagent type.
- **Every where-to-look item answered,** as a finding or "cleared" with a reason. A check refuses an
  answer that skips one; the review command (C10a) calls it.
- **A finding** gives a location, one sentence, consequence, trigger and evidence from C1's closed
  lists, and proof: the failing test with its command and output when reproduced, file-and-line steps
  when traced. Code computes the severity (C1); the reviewer never writes one.
- **Reproduction, sandboxed:** a test in a scratch copy that writes only there, with no network and
  no credentials. The reviewer's own runs use its vendor's sandbox (for Claude, the command sandbox
  set through `--settings`); the review command re-runs each test in its own sandbox before the
  finding counts (C10a). A traced finding is fix later. Then **one capped open search**.
- **Consequence twice.** Jev also picks each reproduced finding's consequence, through a verb in
  fleet-core's registry, and the lower pick applies. When Jev cannot answer, the LLM's pick applies,
  marked "unconfirmed". Disagreements and "unconfirmed" picks show at merge confirmation.
- **Disputes.** The reviewer may dispute a builder's "doesn't apply" or "unaffected" (fix later,
  shown at merge confirmation). It checks recorded reasons but cannot block on them.

Depends on C1 (saga: review records, validation and the A–F formula) and X1a (Record saga's new
review model and its contracts in the lifecycle repository), which names the role.

### Risk

high
The reviewer runs model-written tests here, and "reproduced" is what lets an LLM finding block.

### Inputs inventory

- plan.md (sections above); the roles library at its pin; `roster.py:83-93`; `staffing.json:642`;
  `jev_verbs.py:100`; `role_agent_types.py:329-335`; C1's lists; C6's items; C10a's packet.

### Failure modes / pre-mortem

- **"Reproduced" without a reproduction.** Guard: the review command re-runs the named test (C10a).
- **The reproduction edits the code it tests.** Guard: the copy differs from the head only by tests.
- **A test reaches the network, a credential or outside files.** Guard: the vendor's sandbox, then
  the review command's for the re-run; without that, nothing counts as reproduced (degraded, C3).
- **The configuration steers the review** or rewrites a test's output. Guard: the review run records
  its fingerprint, drift runs measure a new one (K3), and only the command's re-run proves a finding.
- **A later Claude Code release changes `-p` or `--settings`.** Guard: a pinned-argument test.
- **Hidden instructions** in the change. Guard: evidence, never instruction (`lens-reviewer.md:49-55`).
- **The lower pick hides real harm.** Guard: it shows at merge confirmation (C13).

### Stop conditions

- The reviewer's session can commit or push, or a reviewer-written label can set a severity.
- Claude's command sandbox cannot hold the reviewer's test runs to the scratch copy with no network
  and no credentials, or a staffed vendor has no means of its own that can.
- A vendor's launch needs an API key, or works only with instruction files, plugins or hooks off.
- The lifecycle does not yet name the targeted-reviewer role (X1a).

### Out-of-scope / non-goals

- The packet, the re-runs, merging two answers, and recording usage and configuration (C10a); the
  formula and finding identity (C1); starting sessions, the second reviewer, and collecting answers
  and session results (C9).
- Rewriting the review-controller role, and deleting the lens-reviewer role and its staffing row
  (C10b): today's `/code-review` uses them until the switch.
- The reviewer's trace (C15); which components corpus runs may turn off (K3). Screens (C13, C14);
  plan review (C12).

### Files expected to change

- `plugins/saga/references/targeted-reviewer-prompt.md` (new)
- `plugins/saga/references/targeted-reviewer-answer.schema.json` (new)
- `plugins/saga/scripts/reviewer_answer.py` (new; the answer check, the lower pick, "unconfirmed")
- `plugins/saga/scripts/role_agent_types.py`
- `plugins/agent-launcher/roles/targeted-reviewer.md` (new; the wrapper)
- `plugins/agent-launcher/roles/index.json`
- `plugins/agent-launcher/roles/README.md`
- `plugins/agent-launcher/roles/lifecycle-snapshot.json` (regenerated at X1a's pin)
- `plugins/agent-launcher/skills/agent-launcher/scripts/roster.py` (the role mapping)
- `plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py` (the reviewer launch per vendor)
- `plugins/fleet-core/scripts/fleet_commons/staffing.json` (a `targeted-reviewer` row)
- `plugins/fleet-core/scripts/fleet_commons/jev_verbs.py` (the consequence question)

### Tests to add or update

- `plugins/saga/tests/test_reviewer_answer.py` (new): a full answer passes; refused by name: a skipped
  item, a missing location or label, "reproduced" without test, command and output, any severity, too
  many open-search findings. The lower pick applies; "unconfirmed" when Jev cannot answer; `--help`.
- `plugins/agent-launcher/tests/test_launcher_contract.py`: Claude's arguments are pinned (`claude -p`,
  saga's prompt, the sandbox settings); no vendor's launch turns off instruction files, plugins or
  hooks or uses an API key; each sandbox denies writes outside the copy, network and credentials; a
  canned result yields the usage; the configuration fingerprint tracks instruction files and plugins.
- `test_roles_library.py`, `test_roster.py`: the wrapper passes every pinned check; one seat, never
  one per lens. `test_role_agent_types.py`: the role is skipped. `test_jev_cli.py`: covers the verb.

### Context library links

- `plugins/agent-launcher/roles/README.md`; saga's `skills/code-review/references/findings-schema.md`

### Acceptance criteria

- [ ] The prompt requires every item answered, sandboxed reproduction, one capped search, C1's lists,
      no severity, no commit or push, and code and comments read as evidence only.
- [ ] Agent-launcher starts the role on any vendor it staffs with that vendor's normal configuration
      (for Claude, `claude -p`) and returns its usage, vendor, model and configuration fingerprint.
- [ ] Saga's prompt and answer schema and the reviewer's vendor and model are in C2's fingerprinted
      component list; the configuration fingerprint is not, so editing CLAUDE.md fails no check.
- [ ] The reviewer's own test runs write only to the scratch copy, with no network and no
      credentials, through its vendor's sandbox (for Claude, the command sandbox set by `--settings`).
- [ ] A skipped item is refused by name; the lower consequence applies; when Jev cannot answer, the
      LLM's pick is marked "unconfirmed".
- [ ] `role_agent_types.py` lists no subagent type for the targeted reviewer.
- [ ] `python3 -m pytest plugins/agent-launcher/tests -q --import-mode=importlib` passes.

### Verification

```bash
python3 scripts/bundle_fleet_module.py
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
python3 -m pytest plugins/agent-launcher/tests plugins/fleet-core/tests -q --import-mode=importlib
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
git diff --check
```

### Notes / conventions

For the planning step:

- File names are proposals; the role id follows X1a. Each package's changelog and version move, and
  the bundle script refreshes the bundled copies of `staffing.json` and `jev_verbs.py`.
- Per vendor, from its own `--help`: how it runs the role (its non-interactive mode, where it has
  one), where its usage comes from, its sandbox means, and which instruction files and plugin lists
  its configuration fingerprint covers. Per-vendor flags: `launcher.py:192`, `:277`. For Claude, on
  Claude Code 2.1.289: `--settings` (sandbox keys), `--output-format json`, `--no-session-persistence`.
- How the prompt and packet reach the reviewer session, and how agent-launcher finds saga's prompt.
- The open search's cap on findings, and where the scratch copy comes from.
- The staffing row's tier (`lens-reviewer` is `judgment` today); its model is fingerprinted (C2).
- The pin move touches the 17 files under `roles/` that name `e5a2be10`, and `test_roles_library.py:48`.
- This card adds its paths to C2's fingerprinted component list (C2 names its file) in the same change.

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-05-saga-review-redesign/cards/C8-targeted-reviewer.md

### Source context
- Source: docs/brainstorms/2026-10-05-saga-review-redesign/cards/C8-targeted-reviewer.md
- Source type: brainstorm
- Source title: saga + agent-launcher: the targeted LLM reviewer

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/158
- Number: 158
- Created at: 2026-10-05T19:12:23.671236+00:00
