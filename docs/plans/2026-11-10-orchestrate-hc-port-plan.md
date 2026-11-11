---
title: Orchestrate and the agent-launcher scripts drive sessions through herdr core
type: feat
status: active
date: 2026-11-10
origin: the Herdr retirement plan in infiquetra-herdr-console (.claude/plans/2026-11-10-retire-old-herdr.md), unit "port Orchestrate to hc"
backend: inline
---

# Orchestrate and the agent-launcher scripts drive sessions through herdr core

## Summary

Herdr is now two programs: herdr core (`hc`), which runs every terminal on a machine, and the
Herdr app (`herdr-app`), the window that shows several machines' cores as workspaces, tabs and
panes. Old Herdr (the `herdr` 0.9.5 binary with `herdr agent|tab|pane|workspace` and its event
socket) is being removed from every machine, and a session it starts does not appear in the window.

Orchestrate (`plugins/orchestrate`) and the agent-launcher scripts it runs
(`plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py`, `roster.py`, and the
`composer.py` parser they load) create, prompt, read, wait on and close sessions only through old
Herdr. This plan moves every one of those calls to `hc`, starts sessions through the `agents`
launcher's Herdr app path, and keeps every name Orchestrate binds from `launcher.py`
(`REQUIRED_LAUNCHER_NAMES` in `orchestrate.py`).

Jeff approved the move on 2026-11-10 ("move orchestrates launch").

---

## Facts this plan rests on

Each was read from the installed programs on the Mac Studio on 2026-11-10 (hc 0.1.20,
herdr-app 0.1.15), not recalled.

- `hc ls --json` returns `{terminals, machines, hidden_finished}`. Each terminal row carries
  `address`, `agent`, `cwd`, `state`, `status`, `turn` and `where`. Rows from other machines carry a
  `machine/` prefix on the address. Rows carry no name and no labels; `hc get <t> --json` has both.
- **The status has two shapes, by command.** `hc get <t> --json` prints the API's Status record,
  `"status": {"app": "claude-code", "state": "idle"}` (also `kind`, `msg`, `progress`), where `app`
  is the agent's own name for itself and `state` is one of idle, working, done, blocked, error; it
  is `null` until the program reports anything. `hc ls --json` rows and `hc wait --json` print the
  bare word, `"status": "idle"`, and an `hc ls` row leaves `status` out until the program reports.
  The port reads each source with its own reader (`get_status_word`, `row_status_word`), so a
  record of the other shape reads as "no status" rather than half-understood.
- `hc get` `labels` carry `herdr.space` (the workspace id, written when the session is placed) and,
  once a window shows the terminal, `where` ("Workspace / tab"); a session agent-app placed in the
  core also carries `herdr-console.space-name`, the name it asked for.
- The agent names hc reports are `claude-code`, `codex`, `antigravity` and `muse` (observed live).
  `grok`/`grok-build`, `opencode` and `cursor-agent` come from the console's own table
  (infiquetra-herdr-console `cli/herdr-ops/herdr_ops/session_telemetry.py`), not from a live row.
- `hc wait <t> --timeout S --json` prints a WaitResult (`ended`, `reason`, `status`) and exits 0
  on a timeout too. It returns at once when the terminal is not working, and on a status word
  other than working, on exit, or on a message to the caller.
- `hc read <t> --lines N` prints the screen plus N lines of history as plain text. There is no
  styled (ANSI) form on the command line.
- `hc send <t> <text>` pastes and presses Enter. It holds for a person's unfinished draft for up
  to 60 seconds since their last key, refuses a blocked program with exit 9 unless `--force`, and
  from inside an agent's terminal wraps the text in an `<hc from=…>` tag unless `HC_TERMINAL_ID`
  and `HC_SCOPE` are unset (the `herdr` skill, "Typing a shell command into a plain shell").
- `agents` (installed 2026-11-10) defaults a single launch to the Herdr app and runs
  `agent-app prepare … --json`, whose one JSON line is the launch result. Both of its placements
  return `terminal` (an hc address). The window placement adds the app's `tab`, `pane` and
  `space`; the core placement adds `placement: "core"`, `space`, `space_name` and `tab_name`.
  `created_space` says whether the workspace was new. A failure prints `{"error": …}`.
  `agents --dry-run` prints `backend=herdr-app` for an app launch.
- hc never reuses a terminal address on a core ("`t7`: this terminal forever on this core").
- The launcher change that retires old Herdr (infiquetra-herdr-console branch
  `feat/launcher-no-old-herdr`, commit 59ff518, not yet installed) keeps the three things this plan
  relies on: `--app` is accepted, `--no-focus` is accepted for a single launch, and a real launch
  prints only agent-app's one JSON line. On that branch `--no-focus` reaches agent-app, which then
  uses the core placement (`placement: "core"`, the workspace name carried as the
  `herdr-console.space-name` label) so the window does not switch; the installed launcher still
  uses the window placement. The port reads either. `--current` stays a no-op; `--herdr`,
  `--herdr-control-only`, `--herdr-session` and `--new` are refused with exit 2.

---

## Inventory of old-Herdr touchpoints

39 touchpoints in 4 files. Line numbers are `origin/main` at `c24354a`.

### `launcher.py` (agent-launcher), 20 touchpoints

| # | Where | Old call | What it needs | hc / agents equivalent |
| --- | --- | --- | --- | --- |
| 1 | `list_tab_ids` :109 | `herdr tab list --workspace W` | ownership snapshot | `hc ls --all --json`, this machine's addresses |
| 2 | `agent_argv` :541 | `agents --no-focus --current --herdr --herdr-control-only …` | create a tab | `agents --app --no-focus --task … --cwd … [--workspace W] <vendor>` |
| 3 | `agent_row` :651 | via `live_agents` | find one session | match the hc address |
| 4 | `await_ready` :659 | polls `interactive_ready` | wait for readiness | `hc wait <t> --timeout S`, ready on idle or done |
| 5 | `session_has_started`, `took_the_task` :682 | `agent_status` from the list | did it take the task | hc `status` word, same never-started set |
| 6 | `read_pane` :784 | `herdr pane read --source recent-unwrapped`, then `visible` | read screen and history | `hc read <t> --lines N` |
| 7 | `pane_input_inspection` :801 | `herdr pane read --source visible --format ansi` | read the styled screen | `hc read <t> --lines 0`, plain text (gap G1) |
| 8 | `close_run_session` :1007 | `herdr tab close <tab>`, then `herdr tab list` | close what this run made | `hc kill <t>`, then `hc rm <t>` |
| 9 | `workspace_id_for_name` :1056 | `herdr workspace list` | workspace name to id | the launcher's result `space`, else `herdr-app ls` by name (D18) |
| 10 | `pane_account_label` :1144 | `herdr pane read --source visible` | read the statusline | `hc read <t> --lines 0` |
| 11 | `verify_unit_identity` :1270 | kind, cwd, workspace from the list row | check identity | `hc ls` row: `agent`, `cwd`; `hc get`: label `herdr.space` against the result's `space` (D18) |
| 12 | `_record_create_timeout` :1449 | `herdr tab list` | reconcile after a timeout | `hc ls --all --json`, new addresses in the unit's folder |
| 13 | `launch` :1534 | wrapper JSON `tab_id`, `pane_id`, `agent_name`, `reused` | read the receipt | agent-app JSON `terminal`, `tab`, `space`, `created_space` |
| 14 | `PaneWriter` `type_into_pane` :1722 | `herdr pane run <pane> <line>` | type a line | `hc send <t> <line>` |
| 15 | `PaneWriter` prompt door :1743 | `herdr agent prompt <name> <line>` | send a prompt | `hc send <t> <line>` |
| 16 | `live_agents` :1794 | `herdr agent list` | list sessions | `hc ls --json`, this machine's live rows |
| 17 | `current_herdr_workspace_id` :1856 | `herdr pane current --current` | the caller's workspace | `hc get $HC_TERMINAL_ID`, label `herdr.space` |
| 18 | `confirm_preview` :1869 | dry-run `herdr_workspace` contains the caller's id | check the preview | dry-run `backend=herdr-app`, cwd, requested workspace |
| 19 | `close_owned_session` :1886 | via `close_run_session` | close by receipt | unchanged above the hc close |
| 20 | `HERDR_KIND_ALIASES` :224 | Herdr's kind names (`maki`) | map kinds | hc's agent names (`claude-code`, `antigravity`, …) |

### `roster.py` (agent-launcher), 5 touchpoints

| # | Where | Old call | What it needs | hc equivalent |
| --- | --- | --- | --- | --- |
| 21 | `require_herdr_pane` :184 | `HERDR_ENV=1` and `HERDR_PANE_ID` | am I inside Herdr | `HC_TERMINAL_ID` |
| 22 | `wait` :739 | `herdr agent wait <name> --timeout MS` | wait for a seat | `hc wait <t> --timeout S --json` |
| 23 | `_agent_status` :775 | `herdr agent get <name>` | read status | `hc get <t> --json` |
| 24 | `_agent_tail` :790 | `herdr agent read --source recent --lines 40` | quote a blocked screen | `hc read <t> --lines 40` |
| 25 | `workspace_of` :506 | parses `<workspace>:<object>` ids | record the workspace | the receipt's `space` |

### `orchestrate.py` and `herdr_events.py` (orchestrate), 14 touchpoints

| # | Where | Old call | What it needs | hc equivalent |
| --- | --- | --- | --- | --- |
| 26 | import :51 | `herdr_events` | event socket client | removed |
| 27 | `_unit_is_live` :1654 | pane id or agent name in the list | liveness | hc address, then name |
| 28 | `poll` :2761 | agent name in the list | one unit's status | hc address first; an old Herdr id reads `unknown` |
| 29 | `agent_for_worktree`, `rebuild_unit` :2808 | cwd, kind, ids from the list | adopt a stray branch | the same keys from the normalised hc row |
| 30 | `status_snapshot` :4374 | via `settle_reading` | status table | unchanged above `live_agents` |
| 31 | `settle_reading` :4579 | `live_agents` once | one read for all units | unchanged above `live_agents` |
| 32 | `wait_on_agent_waits`, `_popen_herdr_wait` :4779 | `herdr agent wait <name> --until idle\|done\|blocked` | wait on several units | one `hc wait <t>` child per unit |
| 33 | `cmd_wait` :4881 | event socket `pane.agent_status_changed` | wait without polling | the `hc wait` children (row 32) |
| 34 | `retire_run_workspaces` :5894 | `herdr workspace close <name>` | close a workspace | none in hc (gap G7) |
| 35 | `report_unattended_worktrees` :5953 | cwd and name from the list | leaked worktrees | unchanged above `live_agents` |
| 36 | `cmd_clean` liveness :6069 | `live_agents` | liveness | unchanged above `live_agents` |
| 37 | `cmd_adopt` :6307 | `live_agents` | discovery | unchanged above `live_agents` |
| 38 | review routing :1789 | `live_agents` | live workers | unchanged above `live_agents` |
| 39 | `herdr_events.py` | `~/.config/herdr/herdr.sock`, `events.subscribe` | event stream | removed; `hc wait` replaces it |

`composer.py` makes no Herdr call. It parses whatever screen text the launcher reads, so it is
affected through row 7 only.

Kinds of touchpoint: create (1), list and match (6), read status (5), wait (5), read the screen
(5), send text (2), close (3), workspace naming (4), environment (1), ownership (3), imports and
event client (2), kind names (1), preview (1).

---

## Gaps in hc and the Herdr app

- **G1. No styled screen read.** `hc read` is plain text. The composer guard told a client-drawn
  placeholder (styled) from typed text (unstyled) by its colour codes. On plain text every
  non-empty input box reads as typed. Measured on the checked-in captures
  (`plugins/agent-launcher/tests/fixtures/composer-panes.json`): Codex's placeholder reads
  `unclassifiable` with colour codes and `staged` without them; the three Claude captures read
  `empty` both ways. See decision D1.
- **G2. Sessions `agents` starts are not Orchestrate's children.** The window starts them, or
  agent-app runs `hc run --no-parent`, so hc's parent and child links and `hc wait --children`
  do not apply. Ownership comes from the pre-launch address snapshot (D2).
- **G3. `hc ls` rows carry no name and no labels.** The tab name is the second half of `where`;
  labels need `hc get`.
- **G4. One door.** hc has no separate "prompt the agent" and "type into the pane" calls; `hc send`
  is both. S4 confirmed OpenCode's `/variants` picker opens from a pasted line: the launch opened
  it, read it, and refused "requested variant 'high' is not among the 1 options the live picker
  offered", which is right for the default model (Muse Spark 1.3 Contributor, one variant).
- **G5. Tagged sends.** From inside an agent's terminal, `hc send` wraps text in an `<hc from=…>`
  tag, which would stop a leading `/saga:…` command from being read as a command (D5).
- **G6. Kind names differ.** Grok's was not seen live; OpenCode's (`opencode`) was, in S4.
- **G7. No workspace close in hc.** Workspaces are the window's (`herdr-app do space.close`).
- **G8. Another machine.** `agents --app-machine X` runs X's own launcher, whose result names a
  bare `tN` on X. Orchestrate starts every unit on this machine today, so the port refuses a
  result that names another machine rather than guessing (D12).
- **G9. The window's `tab.new` result is undocumented.** Only `terminal` is common to both
  placements, so the port reads only `terminal`, and keeps `tab` and `space` as information.
- **G10. No readiness flag, and silence is ambiguous.** Old Herdr published `interactive_ready`;
  hc publishes the status word, and ready means idle or done. An agent that reports a status says
  nothing until it is past its startup screens: Claude stays silent while its folder-trust question
  is open. hc cannot tell that silence from an agent that never reports one, and `hc send`
  presses Enter, which answers an open question with its highlighted default. The first port read
  silence after the readiness window as "does not report readiness" and sent anyway; the smoke
  test of 2026-11-10 (terminals t9t and t9v on the Studio) answered Claude's trust question
  "No, exit" that way, twice, and Claude quit. Decision D17 replaces that reading.
- **G11. A new terminal's workspace name moves for several seconds.** Measured by the team lead on
  a probe, 2026-11-10: a `--no-focus` launch places the session in herdr core with labels
  `herdr.space=<id>` and `herdr-console.space-name=HC Smoke` and no `where`; within about 3 s the
  window adopts it and writes `where` = "<folder name> / 1"; a few seconds later the seat-board mod
  renames the workspace and tab from the labels and `where` becomes "HC Smoke / <tab>". The first
  port compared the requested name with `where` and read it in that gap: the smoke test's next
  launch failed with "session workspace 'hc-smoke-repo' does not match requested workspace
  'HC Smoke'" and closed its owned session. Decision D18 replaces the check.

---

## Decisions made on Jeff's behalf

Each one changes how Orchestrate behaves, so each takes the conservative side.

- **D1. The input-box guard keeps its stop on plain text, except for a vendor's own placeholder,
  matched whole.** Non-empty text the parser reads as typed is still a staged-input stop, never
  sent behind. A box whose whole content is exactly a placeholder the vendor draws in an empty box
  is read as empty, and the receipt records it (`input_box: "empty"`,
  `input_box_placeholder: "<the text>"`). The table (`KNOWN_PLACEHOLDERS` in `launcher.py`) comes
  from the installed binaries, 2026-11-10: Codex 0.167.1 draws "Ask Codex to do anything" (new
  session) and "Ask a follow-up question" (the string beside it); it does not rotate. Claude Code
  2.1.322 draws `Try "<example>"`, rotating among eight examples: four fixed, matched exactly, and
  four naming a file from the project's git history, matched by their template with the file as one
  token. OpenCode v2.2.7 draws `Ask anything… "<example>"` (three examples), `Run a command…
  "<example>"` in shell mode (three more) and "Ask anything, / for commands, @ for context"; they
  are listed, but the parser has no marker for OpenCode's box, so the guard reads OpenCode as
  `unsupported_vendor` and never stops an OpenCode write on staged input (a later write to an
  OpenCode unit is sent with a note). Anything else, including a placeholder with typed text
  beside it, stays a stop. Found
  by the smoke-test re-run: a `redeliver` into a Codex session showing "› Ask Codex to do
  anything" refused as staged input (24 chars), which would have stopped every redeliver, resend
  and routed repair to a Codex unit. Rejected: reading every non-empty plain box as
  `unclassifiable` (always sends), which removes the stop the guard exists for; and prefix or
  substring matching, which would let a draft that starts with the placeholder's words through.
- **D2. Ownership is the pre-launch address snapshot.** `owned` is true only when the launcher's
  terminal address was absent from this machine's terminal list (finished ones included) taken
  just before the launcher ran. hc never reuses an address, so the proof is exact. No label is
  written: the run record stays the only authority on what may be closed.
- **D3. `tab_id` holds the terminal address.** It is the identity a close acts on, so every
  existing tab rule (merge refuses while a unit records one, `clean` closes it, `close` matches it
  against the receipt) keeps working. The app's own tab id goes in the receipt as `app_tab`.
  `pane_id` holds the same address, so the run record's shape is unchanged.
- **D4. Close is `hc kill`, then `hc rm`.** A terminal hc no longer has, or one already finished,
  counts as closed. A recorded id that is not an hc address (an old Herdr tab) is never handed to
  hc; the close fails with a note naming old Herdr.
- **D5. Every hc call runs with `HC_TERMINAL_ID` and `HC_SCOPE` removed.** Sends arrive untagged,
  so a leading saga command still works, and a wait is not ended by a message to the operator's
  own session, which matches old Herdr's waits.
- **D6. A blocked session refuses a send, and Orchestrate never forces it.** hc's exit 9 becomes a
  named stop telling the operator to read the screen. Old Herdr fell back to typing into the pane,
  which could answer the dialog.
- **D7. A write may take 90 seconds** (was 30): hc holds a send for up to 60 seconds while a
  person's draft is open, and a timeout is a stop saying the line may or may not have arrived.
- **D8. The long-task file handoff applies when the session reports no status**, hc's form of
  "does not report readiness", which is when old Herdr's prompt door refused and the pane fallback
  used the handoff. Since D17 this applies only to a vendor confirmed never to report a status,
  and none is confirmed today.
- **D9. An old Herdr id reads as `unknown`, never `gone`.** A run started under old Herdr and read
  after the move keeps its units running rather than settling or reaping them on missing data.
- **D10. `wait` uses one `hc wait` per running unit.** The event socket client
  (`herdr_events.py`) is removed. hc returns from a wait on `error` as well as `blocked`; both are
  reported on first sight (old Herdr's waits did not wake on error at all), and a unit that has
  exited is dropped from the wait instead of being waited on again.
- **D11. `clean` no longer closes workspaces.** `retire_run_workspaces` reports any recorded
  workspace as left for the window. No code path has ever recorded one (`workspaces_created` is
  only loaded and saved), so this affects only a hand-edited record.
- **D12. Only this machine's terminals count.** Rows from other machines are dropped the moment
  `hc ls` is read, and a launch result naming another machine is refused.
- **D13. Launch with `--app` and refuse a preview that is not the app.** `agent_argv` passes
  `--app --no-focus --task --cwd [--workspace] <vendor>`. `launcher.py preview` and `launch` refuse
  unless the dry run reports `backend=herdr-app`, so nothing silently lands in old Herdr.
- **D14. An unreported agent kind does not stop an owned launch.** Before an agent reports its
  status, hc shows the foreground program (a shell, or Claude's version string). A known kind that
  names another vendor still closes the session and stops, as before. An unknown kind stops an
  unowned session, as before, and is recorded as unconfirmed for an owned one.
- **D15. The agent-launcher's `SKILL.md` and `README.md` are not edited here.** Both are bound by
  digest to the mutation proof (`tests/test_agent_launcher_rule_audit.py`, `PROOF_DOCUMENT`), and
  open PR #310 (`fix/agent-launcher-herdr-app`) rewrites `SKILL.md` with its own proof. Editing
  them here would force a second proof that conflicts with #310's. A follow-up after #310 merges
  updates both documents and re-runs the proof once.
- **D17. A session that reports no status is not sent anything** (added after the smoke test,
  G10). After the readiness window, a session whose vendor is not confirmed silent and that still
  reports no status is "not ready": nothing is sent, nothing is closed, the launch stops with
  "<task> has not reported a status after 30 s; a startup question such as folder trust may be
  open: read it with `hc read tN`", and the receipt records `status_reported: false`,
  `readiness: false` and `prompt_delivered: false`, so the retry door can deliver once the
  question is answered. `PaneWriter` holds every later write to the same rule. Only a vendor
  confirmed never to report a status (`VENDORS_WITHOUT_STATUS`, empty today) may be sent a line
  without one, and only after `hc read` shows no selection menu (a `❯` numbered choice, or
  "Enter to confirm" / "Enter to select"); a screen that cannot be read refuses too. Claude Code,
  Codex, Antigravity and Muse were each seen reporting a status on a live Studio terminal on
  2026-11-10, and OpenCode v2.2.x in the smoke test's S4 (`{"app": "opencode", "state":
  "idle"}`). Grok was not seen live, so it is held to the not-ready rule until one of its
  sessions is watched.
- **D18. The workspace is checked by id, never by name** (added after the smoke test, G11). The
  terminal's `herdr.space` label is compared with the `space` id in the launcher's result; when
  the result names none, with the id of the one workspace of that name on this machine from
  `herdr-app ls` (read-only; two of the name, or none, give no id). Both ids are written at
  placement and do not move. A mismatch still closes the run-owned session and stops; a terminal
  with no `herdr.space` label yet, or no expected id, leaves the workspace unconfirmed. The name
  (`where`, else `herdr-console.space-name`) is kept in the receipt as `workspace_shown`, display
  text only.
- **D16. No version bump here.** The repository bumps versions only in a release pull request
  (`chore(release)`), so both changelogs carry the change under `[Unreleased]`, marked breaking.
  The release must make both major versions and raise Orchestrate's Claude adapter floor for
  agent-launcher (`>=1.7.2` today) to the agent-launcher version it ships, because a launcher
  below it drives old Herdr.

---

## Units

1. **launcher.py** — rows 1 to 20, with `launcher.run` stripping the two caller variables for
   `hc` (D5). Tests: `plugins/agent-launcher/tests/test_launcher_contract.py` fakes move from
   `herdr` argv to `hc` argv and hc's JSON shapes.
2. **roster.py** — rows 21 to 25. Tests: `plugins/agent-launcher/tests/test_roster.py`.
3. **orchestrate.py** — rows 26 to 39; `herdr_events.py` removed and dropped from
   `ports/orchestrate.json`. Tests across `plugins/orchestrate/tests/`.
4. **Release notes** — `[Unreleased]` CHANGELOG entries (D16), Orchestrate's README, SKILL.md
   and command text, and engineering-journal entries.

---

## Still on old Herdr after this plan

- The agent-launcher `SKILL.md` and `README.md` text (D15).
- The voice plugin (`plugins/voice`), which binds to old Herdr panes; out of scope here.
- Saga's plan skill mentions old Herdr in prose (`plugins/saga/skills/plan/SKILL.md`).
- `plugins/orchestrate/tests/fixtures/agent-launcher-1.7.0/`, a frozen copy of the old launcher
  kept to test the companion floor; it is a fixture, not a runtime path.

---

## Live smoke test

Jeff approved it on 2026-11-10 and the team lead ran it from PR #312 with
`ORCHESTRATE_AGENT_LAUNCHER` pointed at the launcher from `feat/launcher-no-old-herdr`. S1 and S3
passed. S2 failed twice: in a new scratch folder Claude opened its folder-trust question and
reported no status, `await_ready` spent its 30 s, and the prompt's Enter answered the question
"No, exit", so Claude quit and the receipt said `prompt_delivered: false` (terminals t9t and t9v).
D17 fixes it. Re-run S2 twice: once in a new folder, expecting the stop "hc-smoke has not reported
a status after 30 s; a startup question such as folder trust may be open: read it with
`hc read tN`", the tab left open and the receipt showing `status_reported: false`; then answer the
question in the tab and run `launcher.py redeliver --receipt-json receipt.json` with the same
flags, expecting the reply and `prompt_delivered: true`. Then a folder Claude already trusts,
expecting S2 as written.

The trusted-folder run then found G11: the launch failed with "session workspace 'hc-smoke-repo'
does not match requested workspace 'HC Smoke'" and closed its own session, because the check read
the window's `where` label before the rename. D18 fixes it; that re-run should confirm
`workspace` in `confirmed_against_herdr`, with `workspace_shown` holding whichever name the window
showed at that moment.

The re-run on 76af887 passed S2 for Claude (reply "ready", workspace confirmed, close removed the
terminal) and the not-ready stop fired for Codex's "Trust this folder?" question. The recovery
then found the D1 gap: after the question was answered, `redeliver` refused because Codex's
placeholder read as staged input. The known-placeholder match fixes it, and `redeliver` now takes
`--vendor`, `--task`, `--cwd` and `--workspace` from the receipt when they are not passed (a
`--vendor` the receipt contradicts is refused). Re-run: answer Codex's question, then
`launcher.py redeliver --prompt "..." --receipt-json receipt.json`, expecting
`input_box_placeholder: "Ask Codex to do anything"` and `prompt_delivered: true`.

Steps, from a Herdr terminal on the Studio, in a scratch repository:

- S1. `python3 launcher.py preview --vendor claude --task hc-smoke --cwd <scratch repo>`: expect
  `backend=herdr-app` and the folder.
- S2. `python3 launcher.py launch --vendor claude --task hc-smoke --cwd <scratch repo> --workspace "HC Smoke" --prompt "Reply with the word ready and stop." > receipt.json`:
  expect a tab named hc-smoke in a new "HC Smoke" workspace, the reply, and a receipt with
  `owned: true`, `pane` and `tab_id` both the hc address, and `prompt_delivered: true`.
- S3. `python3 launcher.py close --receipt-json receipt.json`: expect the terminal gone from
  `hc ls` and the tab gone from the window.
- S4. The same three with `--vendor codex` (D1: Codex's placeholder reads as empty) and
  `--vendor opencode --variant high` (G4: the `/variants` picker through `hc send`).
- S5. A one-unit Orchestrate run with `go`, `wait`, `settle` and `clean` on the same scratch
  repository.
