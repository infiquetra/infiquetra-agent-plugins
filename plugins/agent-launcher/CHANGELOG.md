# Changelog

## [1.7.1] - 2026-09-22

1.7.1 — imported from infiquetra-claude-plugins@acc99fe71e25ad8a898eace7033051a7f1c3079e (upstream 1.7.0); authored here from this commit; no provenance manifest from now on.

The roles library is unchanged and still written against infiquetra-sdlc revision `5efc869f`.

### Changed

- Removed the Claude plugin-cache fallback (`~/.claude/plugins/cache/*/agent-launcher/`) from `SKILL.md` and this README. That ladder resolved a Claude install instead of this package. Claude still reaches the scripts through `$CLAUDE_PLUGIN_ROOT/skills/...`, because skills stay at the package root. Every other harness runs `python3 skills/agent-launcher/scripts/launcher.py` from the package root.
- Removed the personal keychain service name and the home-lab Ansible pointer from the skill. Credentials are named only as environment variables.
- The three manifests agree on 1.7.1. The patch bump marks the authored cut of upstream 1.7.0.
- The slug example in `claude_project_slug` and the statusline example in `pane_account_label` use inert names. Account-label behaviour is unchanged: the label is read from the statusline beside whatever `USER` the process has.

### Dropped tests

These came from upstream and their premise is the upstream repository (the Orchestrate plugin beside this one, that repository's journal, or its marketplace), so they are not carried:

- `test_orchestrate_has_no_private_launcher_copy`
- `test_degraded_path_binds_settle_and_review_names`
- `test_orchestrate_subprocess_cli_is_not_the_launcher_cli`
- `test_orchestrate_ingests_this_script`
- `test_orchestrate_sorts_launcher_cache_versions_numerically`
- `test_orchestrate_rejects_a_launcher_below_its_declared_floor`
- `test_orchestrate_declares_agent_launcher_dependency_and_breaking_version`
- `test_shipped_launcher_defines_every_name_orchestrate_requires`
- `test_skill_bound_name_list_matches_required_launcher_names`
- `test_journal_43_pane_citations_are_named_not_reproducible`
- The Orchestrate half of `test_every_pane_write_goes_through_the_one_writer` and `test_forcing_the_guard_off_at_each_write_site_is_observed` (the launcher half stays)
- The journal and Orchestrate assertions inside `test_release_and_journal_record_the_composer_contract` (the changelog, skill, and `composer.py` assertions stay)
- From upstream `tests/test_agent_launcher_plugin.py`, every test whose subject is Orchestrate's install, ingest, floor, or marketplace registration. Kept, rewritten under `plugins/agent-launcher/tests/test_plugin_surface.py`: `test_agent_launcher_packaged_files`, `test_standalone_launcher_missing_composer_is_a_named_stop`, `test_standalone_launcher_broken_composer_is_a_named_stop`. Dropped by name: `test_agent_launcher_metadata_is_marketplace_registered`, `test_installed_layout_names_cache_dirs_from_the_manifest`, `test_orchestrate_declares_agent_launcher_dependency_in_metadata`, `test_orchestrate_skill_matches_the_deferred_floor_failure_contract`, `test_orchestrate_readme_and_command_agree_the_launcher_floor_is_enforced`, `test_orchestrate_skill_states_the_staged_input_recovery_runbook`, `test_installed_orchestrate_roster_fails_fast_without_launcher`, `test_installed_orchestrate_expand_and_go_fail_before_worktree_creation`, `test_installed_orchestrate_with_discoverable_launcher_passes_preflight`, `test_read_only_help_and_roster_survive_a_stale_launcher_while_go_enforces_the_floor`, `test_a_launcher_root_that_lacks_the_bound_names_is_the_named_companion_fault`, `test_missing_composer_is_deferred_and_reported_without_a_traceback`, `test_ingested_launcher_broken_composer_uses_the_same_named_contract`, `test_internal_launcher_failure_uses_the_same_deferred_named_contract`, `test_installed_cache_discovery_selects_and_validates_the_highest_numeric_version`, `test_the_companion_floor_matrix`, `test_plugin_root_discovery_selects_the_highest_numeric_version`, `test_bad_agent_launcher_root_override_exits_with_the_named_message`, `test_malformed_floor_requirements_exit_with_the_named_message`, `test_each_companion_fault_names_its_own_cause_and_remedy`, `test_a_launcher_that_fails_mid_file_binds_nothing`, `test_installed_orchestrate_help_describes_orchestrate`, `test_the_degraded_stub_roster_covers_every_referenced_launcher_name`, `test_the_four_shared_constants_agree_between_orchestrate_and_the_launcher`, `test_every_sibling_plugin_path_goes_through_the_layout_helper`, `test_a_name_only_stub_is_not_a_usable_companion`, `test_a_launcher_root_that_lacks_a_read_path_bound_name_degrades_status`, `test_check_does_not_agree_when_liveness_was_not_performed`, `test_highest_cache_version_that_dropped_a_bound_name_is_not_a_write_companion`, `test_orchestrate_install_sentence_names_the_agent_launcher_floor`, `test_write_gate_comments_name_the_live_write_path`, `test_live_docs_do_not_present_deleted_say_or_used_pane_as_current`.

`tests/test_roster.py` is carried. A test that needs saga's `run_record.py` or Fleet Core's `staffing.json` skips when that file is not in this checkout, because those packages are imported on other branches. It does not fail for their absence.

## [1.7.0] - 2026-09-19

**Bumped from 1.6.0**, the agent-launcher version on the integration branch `origin/parent/1018`
when this card branched; saga's 0.164.0 entry names that same head by commit. The roles library this
helper briefs its sessions from is unchanged and still written against `infiquetra-sdlc` revision
`5efc869f`.

### Added

- `skills/agent-launcher/scripts/roster.py`: the roster helper (issue #1024). `up` reads an issue's
  run record, resolves every role its staffing plan names to a vendor, model, effort and prompt from
  the roles library, and creates one named herdr pane per role **through `launcher.py`**, so every
  pane carries an ownership receipt. `wait` waits for those panes under a caller timeout. `down`
  closes exactly the panes the run record says this helper created, and nothing else.
- A `roster_entry.v1` row per created pane in the run record's `roster` array, carrying the role,
  the pane, tab and workspace identifiers, and the absolute path of the launch receipt that proves
  ownership. The receipts live beside the run record, outside every worktree, so removing a unit's
  worktree cannot strand a pane no one can prove the right to close.
- `--account company|personal` on `up`, because the staffing plan carries tiers and an account is
  not one: without it the helper appends no account flag and the wrapper's own default applies,
  which is the personal account. A staffing row carrying its own `account` overrides the flag for
  that role. Found by running the helper against the live herdr server rather than by reading it.
- `A whole roster from a run record` in `SKILL.md`: the helper's contract, its refusals, and the
  rule that `down` is the only teardown.

### Guards

- `up` is idempotent per role, so re-running it after an interruption repairs the roster rather than
  doubling it; `down` never reads `herdr agent list` to decide what to close, skips any row whose
  ownership receipt is gone or whose `created_by` is not this helper, and refuses the pane it is
  itself running in; a blocked role is reported with its output tail, never answered; every wait
  carries a timeout and takes herdr's own settled-state default; every subcommand refuses outside a
  herdr pane with exit 4; and a staffing role the roles library has no prompt for — `merging-worker`
  is the one that exists today — is a named refusal rather than an invented briefing.

## [1.6.0] - 2026-09-19

### Added

- **A roles library at `roles/`, one reusable prompt per lifecycle role (#1022).** Fourteen prompts plus a README stating the contract each follows: the role and its authority boundary, the inputs it reads from the run record, the handoff contract it posts, and its stop rule. Written in the vocabulary of `infiquetra-sdlc` at revision `5efc869f`, read at that pin with `git show` so a checkout on a moving default branch still serves the pinned documents.
- **Fourteen is the lifecycle's fifteen roles minus the Human Operator**, who is a person rather than a session. The two historical role identifiers are carried in frontmatter rather than in filenames: the Architect's identifier is `orchestrator` and the Delivery Manager's is `controller`.
- **`roles/lens-reviewer.md` carries a shared reviewer half plus one section per lens**, keyed to the fifteen identifiers in the lifecycle's lens catalogue. It states no threshold of its own; the catalogue owns the strictness ladder.
- **`tests/test_roles_library.py`**, which reads the expected role set from the README's map and the lens, contract and role identifiers from the sibling lifecycle checkout when one resolves.

### Notes

- Nothing here spawns, orders, gates or aggregates a role; the roster helper and the run chain consume these prompts later.
- The `team-execution` plugin's 25 agent prompts and two criteria documents were the source material and are unchanged by this release. The README accounts for where each one's substance went.

## [1.5.2] - 2026-09-16

### Changed

- **SKILL.md's bound-name list names `AccountMismatchError` and matches Orchestrate's `REQUIRED_LAUNCHER_NAMES`, including `ComposerState` (#1003).** Removing or renaming one remains a major change that moves Orchestrate's declared floor.

## [1.5.1] - 2026-09-16

### Changed

- **A blank-separated empty marker under a staged draft is a decoy, not an empty live box (#961).** `inspect_composer` walks trailing empty markers and returns the earlier staged inspection when every row between them is blank or another empty decoy. A content row between an echoed prompt and a last empty box still reads empty (CORR-05).
- **The structural pane-write detector reports the enumerated evasion shapes (#972).** `_raw_door_calls` follows argv through lists, tuples, concatenation, assigned constants, f-strings, aliases, keyword `args=`, and `subprocess.run`, plus `._raw` / `._type` and `w.write`. The snippet test drives that helper with no special-case returns.

## [1.5.0] - 2026-09-16

### Changed

- **Composer classification no longer treats a quoted Claude continuation as empty, and an adjacent painted empty marker cannot authorize a write (#1002).** A still-empty Claude box whose next row begins with another vendor glyph is that draft. An immediately adjacent empty marker under a staged block returns the staged inspection. A blank or content row between blocks still lets last-block-wins keep an empty live box empty.
- **`done` is a started session. `redeliver` will not send into one (#1002).** `NEVER_STARTED_STATUSES` is `(None, "idle", "unknown")`. A receipt that already delivered, or that is missing `unit_name`, `pane`, `tab_id`, `owned`, or `agent_name`, is refused at exit 2.
- **`PaneWriter.write` owns both Herdr doors as nested functions; `_raw` and `_type` are gone (#1002).** A failed or timed-out composer read refuses the write. The structural test is a net for enumerated AST shapes, not a proof of impossibility.
- **OpenCode picker options are the effort ladder; the typed-token echo is not session confirmation (#1002).** Notes and stops no longer interpolate scraped tokens. `picker_menu_only` does not write a verified note.
- **`herdr workspace list` is bounded, account labels are read from the visible tail, inspect windows have both a row cap and a 131072-byte cap, and task-file writes refuse symlink escape (#1002).** Empty-box receipts drop a stale `input_box_text_chars`.

## [1.4.0] - 2026-09-02

### Changed

- **Every line that enters a session goes through one door, `PaneWriter.write`, and that
  door owns the inspection (#907).** Both raw Herdr write calls exist only inside the class;
  the OpenCode picker's two keystrokes, each setup slash command, the task, each resend, and
  every prompt Orchestrate sends later are calls on the same writer, which inspects before
  each write from its own record of having written. An uninspected write can no longer be
  introduced by forgetting a flag. `say()` is removed. On an owned OpenCode launch the picker
  opening is the one exempt first write; the variant selection and the task are inspected.
- **`redeliver` retries an undelivered prompt as well as a staged-input stop, refuses by exit
  code, and reads the session's status in the same vocabulary as delivery (#907).** A receipt
  with `prompt_delivered: false` is retryable. Refusals -- an empty `--prompt`, another task's
  receipt, neither retryable marker, no pane -- exit 2 before any Herdr call; a retry whose
  prompt was not observed to be taken exits 1; success exits 0. A session reporting `done`,
  `unknown` or no status has not started and is retried; only a visibly started one is refused.
  The dead `pane_id` alias is gone; the README documents the receipt's key set.
- **The composer parser is handed at most `PANE_INSPECT_MAX_LINES` rows, never a byte cut
  (#907).** A byte cut could land inside the marker row and turn a staged draft into `not_found`.
- **The picker refusal reports the count of options, not the scraped tokens (#907).**
- **The OpenCode variant confirmation records where the token was seen (#907).**
  `variant_confirmed_from` is `session` or `picker_menu_only`; the preflight confirms the
  variant only in the first case.
- **The pane-typing door's timeout names the ambiguity like the prompt door (#907).**
- **The delivery warning names the recovery (#907).**

## [1.3.0] - 2026-09-02

### Added

- **`redeliver` subcommand (#907).** The standalone retry for a staged-input stop. It takes the
  tab, pane and ownership from the receipt the stop wrote and the task from the same flags
  `launch` takes; it refuses a receipt written for another task, one that does not record a
  staged-input stop, or one with no pane; it never runs the wrapper create; and it exits
  nonzero when the prompt was not observed to be taken. Before, the only visible recovery was
  a second `launch`, which created a second session over the first owned tab.

### Changed

- **Every pane write after the first is inspected, whatever the ownership (#907).** The write
  half of the guard predicate now records that the launcher wrote into the session, not which
  door carried the line. Before, a successful `herdr agent prompt` left it false, so an owned
  session's two resends -- and every write of a redelivery -- went out with no composer
  inspection. The rule has one owner, `should_guard_pane_write`, which Orchestrate's later
  senders call too. The 1.2.2 line below describing the resend rule as "unowned or the launcher
  already typed into it" described the defective predicate. *In this release the OpenCode
  picker's two writes sat outside the rule and never set the write flag, so an owned OpenCode
  launch still made three uninspected writes; 1.4.0 closes that by construction.*
- **`redeliver()` refuses a session that has left idle (#907).** It inherits the resend loop's
  own precondition: a working, blocked or gone session may already hold the task, so the retry
  route closes as `prompt_undelivered` for the operator to check instead of risking a second
  delivery.
- **Both pane writes carry a timeout, `PANE_WRITE_SECONDS` (#907).** They were the only Herdr
  calls with no bound. A prompt that times out is a named stop and never falls through to the
  pane door.
- **The composer parser is linear on unterminated OSC sequences, and is handed at most
  `PANE_INSPECT_MAX_CHARS` characters from the tail of the pane (#907).**
- **`say()` and `send()` return nothing; `pane_input_text()` is removed (#907).** No caller was
  left that could use either safely.

## [1.2.2] - 2026-09-02

### Fixed

- **A broken composer parser is one named stop in both entry modes (#907).** A parser file
  that raises on import stops `launch` with the exception type and message, standalone and
  ingested by Orchestrate, instead of escaping as a traceback.
- **A failed tab close records its note once (#907).** `close_run_session` is the single
  writer of the close-failure note and tests membership on the whole note, so repeated
  failures no longer stack copies.

- **The composer row rule is one classification per physical row (#907).** A row
  continues an open block when it is bordered or when it is unbordered and
  indented past the marker column; a blank, a horizontal rule, a marker, or a
  row at or left of the marker ends the block.
- **A resend inspects when the pane is unowned or the launcher already typed
  into it (#907).** The inspection sits immediately before the write it
  authorises.
- **Adjacent glyph-led rows stay `unclassifiable` when the viewport cannot prove
  a new box (#907).**
- **`input_box_text_chars` is the visible length of the absorbed draft (#907).**
  One definition, recorded only when the box is staged.

## [1.2.1] - 2026-08-31

### Fixed

- **Composer geometry no longer turns pane chrome into a draft or an ambiguous draft into empty
  (#907).** Paired borders are structural, blank and merely indented rows no longer become input
  continuations, and adjacent glyph-led rows produce `unclassifiable` when the viewport cannot
  prove whether they are a new box. Marker detection remains anchored at the row prefix.
- **Every unowned-pane resend performs a fresh input inspection (#907).** A successful agent-prompt
  send no longer lets a later pane fallback bypass the staged-input guard.
- **The composer loader owns its source location and produces a named stop (#907).** Standalone and
  Orchestrate-ingested launchers resolve `composer.py` from the compiled launcher path without a
  caller-injected global; missing or unreadable parser files no longer escape as tracebacks.
- **The serialized input-box receipt is now documented as a complete contract (#907).** The skill
  and README enumerate every `input_box` value and the conditional redacted
  `input_box_text_chars` field.

## [1.2.0] - 2026-08-30

### Fixed

- **The unowned-pane guard no longer mistakes scrollback for the live composer (#907).** Composer
  parsing now lives in a bounded terminal parser, selects the last block positionally, terminates
  it at the first non-continuation row, understands bordered composers and per-attribute terminal
  resets, and covers the complete vendor roster. Claude, Codex, Grok, Agy, and Qwen have verified
  glyphs; Muse and OpenCode are explicit unsupported cases. Receipts distinguish
  `unclassifiable`, `not_found`, `unsupported_vendor`, `read_failed`, and `read_timeout`; an
  unambiguous staged draft still stops with only `input_box_text_chars`, never the text.
- **Launch and teardown failures retain recoverable session identity (#907).** A create timeout
  reconciles the target workspace's tab set into a minimal receipt, a genuine wrapper exit 124 is
  no longer confused with a synthesized timeout, and an already-absent owned tab is an idempotent
  successful close. Pane reads and close calls are bounded.
- **Receipt evidence now says exactly which checks ran (#907).** One receipt shape is completed in
  place, empty permission-token lists no longer claim argv confirmation, malformed receipt files
  produce a named recovery stop, and transcript files removed during preflight are skipped.

## [1.1.0] - 2026-08-30

### Fixed

- **A hanging session create is a named stop, not a blocked launch (#890).** `launch` runs the
  wrapper under an explicit deadline (`LAUNCH_CREATE_SECONDS`, 120 seconds — larger than every
  other deadline because it may reach another machine and cold-start a vendor CLI) and stops with
  a named message when the create times out or exits nonzero, instead of blocking without bound.
- **A pane this launch did not create is inspected before it is prompted (#897).** A session
  whose tab already existed may hold text somebody staged in its input box, and a prompt typed
  behind it can submit that text. The guard reads the box with styling intact and stops on
  unambiguous staged text, recorded only by character count and never cleared. Fully styled text
  can be byte-indistinguishable from a placeholder; version 1.2.0 records that case separately
  instead of claiming a distinction. The guard keys on tab ownership, not the wrapper's `reused`
  bit, which names the workspace and would inspect the ordinary create path.
- **A declared permission is honoured and confirmed, never silently downgraded (#896).** A
  permission value outside the vendor's map stops with a named message instead of falling back to
  the auto flags, and preflight confirms the declared posture against the launch argv, recording
  `permission_resolved` in the receipt distinctly from the requested value.
- **A stale transcript can no longer certify a launch's account (#889).** `launch` captures the
  create instant and passes it as a recency floor, so a statusline-silent session is confirmed
  only from a transcript written at or after that instant (one second of mtime slack absorbs
  filesystem granularity). The receipt records `account_evidence` — statusline, transcript, or
  none — beside the requested account.
- **A failing owned close is surfaced instead of swallowed (#888).** `close_run_session` returns
  the Herdr result and records a failing close (returncode and error text) on the unit note;
  `close_owned_session`, the CLI-facing variant, exits nonzero on the same failure. Unowned
  sessions still close nothing and report nothing.
- **A missing receipt path stops with a cause and a recovery, not a traceback (#887).**
  `close --receipt-json` on an argument that is neither an existing file nor inline JSON raises a
  `SystemExit` naming the path and the remedy. Inline JSON — object or array — keeps its existing
  behaviour, including the `receipt must be a JSON object` stop.
- **The skill stops overselling `--dry-run` (#880).** The guidance now names what dry-run confirms
  (resolved working directory, Herdr workspace, flag ordering, exact command) and what it does not
  validate (model, reasoning effort, account), and documents the real preflight — a bounded live
  launch with a read-back — under an ordering rule with secret-safety safeguards.

## [1.0.0] - 2026-08-25

### Added

- **Portable single-session launch contract (#777).** New plugin owns create-via-`agents`,
  verify-via-Herdr, prompt delivery, and owned cleanup. An ordinary session can launch one
  verified agent without starting an Orchestrate run. Orchestrate consumes the same module
  (`skills/agent-launcher/scripts/launcher.py`) and no longer keeps a private copy of the
  launcher seam. Explicit dependency on the canonical `herdr` skill for every interaction
  after the session exists; this plugin does not duplicate it. The Agent Plugins port is
  tracked at infiquetra-agent-plugins#22 and does not gate this release.
