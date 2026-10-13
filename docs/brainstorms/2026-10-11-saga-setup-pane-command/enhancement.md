# saga: a setup command that opens the setup pane directly

### Objective

Give the operator a slash command, registered by saga's Claude Code mod, that opens the setup pane at once and runs
the survey, the tool installs and the optional steps from the pane itself. The agent stays out of the loop unless the
operator asks for it.

### Intent

Today `/saga:setup` loads a skill. The agent then calls the `mcp__saga__setup` tool, which opens the pane and waits
for the operator, and the result travels back through the agent. That round trip is slow, it depends on the tool
result surviving the session's output check (#218 fixed one break there), and nothing happens until the agent's turn
comes round. The review pane (`/review-view`) and the plan viewer already register their own commands and open their
panes directly; setup should work the same way.

The operator asked for this on 11 October, for #147's saga release, so that the release ships a friendlier setup
together with the `outcome-schedule` step the operator installs from it.

### Out-of-scope / non-goals

- Removing the `/saga:setup` skill or the `mcp__saga__setup` tool. Harnesses without Claude Code mods, and agent-led
  setup, keep using them unchanged.
- Adding install commands to tool rows that have none, or changing which tools the survey lists.
- The repository questions the setup skill asks (the `questions` section of setup-extensions.yaml); the pane links
  to `/saga:setup` for those.
- #220 (the schedule pinning the installing version).

### Files expected to change

- plugins/saga/com.infiquetra.claude/mods/setup-pane.tsx
- plugins/saga/com.infiquetra.claude/mods/setup-pane.test.tsx
- plugins/saga/com.infiquetra.claude/mods/run-record.ts
- plugins/saga/com.infiquetra.claude/mods/run-record.test.ts
- plugins/saga/com.infiquetra.claude/types/index.d.ts
- plugins/saga/skills/setup/SKILL.md
- plugins/saga/README.md
- plugins/saga/CHANGELOG.md

### Tests to add or update

- The command is registered at session start with a name that collides with no saga skill or built-in command, and
  running it opens the setup pane without any tool call.
- Opened by the command, the pane runs the survey itself and renders tools, their state, and the optional steps; a
  survey failure renders as a plain message with the script's last lines, never a crash.
- An install or a step started from the pane shows running, then done or failed, per row; a failure shows the last
  lines of output; the survey refreshes after each action so done states are current.
- Closing the command-opened pane returns nothing to the agent and leaves no pending tool call.
- When the build exposes a way for a mod to hand text to the session, a failed row offers "Ask Claude", which hands
  over the row, the command and the output tail; when it does not, the failure text is selectable for the operator
  to paste. Either way, a test covers the behaviour.
- The tool path (`mcp__saga__setup`) keeps every behaviour #218 tested, and the two paths share one survey, install
  and step implementation.

### Context library links

_none_

### Acceptance criteria

- [ ] Typing the command in a Claude Code session opens the setup pane with no agent turn: `claude plugin test
  plugins/saga` covers it, and a live session on Claude Code 2.1.296 shows it.
- [ ] From the command-opened pane, the operator sees each tool's state and each optional step with its done state,
  and can run a step; the step runs from the saga plugin root.
- [ ] Each install or step shows its progress and result in the pane, and a failure shows its output tail.
- [ ] `/saga:setup` and `mcp__saga__setup` behave exactly as after #218; the setup skill and the README name the new
  command for Claude Code users.

### Verification

```bash
claude plugin validate --strict plugins/saga
claude plugin test plugins/saga
python3 -m pytest plugins/saga/tests/test_saga_setup.py
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
```

Then, in a live Claude Code session with this branch's saga loaded, type the command and confirm the pane opens
before any agent turn.

### Risk

medium

The change touches the setup pane shared with the merge-free tool path; tests pin the tool path's behaviour from #218.

### Notes / conventions

Follow the review pane's pattern (`review-pane.tsx`: `$.command.register` at `session.start` with `immediate: true`,
answered by a `command.run` hook). Never press Run on a step in a live test: it installs a launchd job on the
operator's machine. Never disable or change the operator's installed plugins to test; use a scratch config directory.
