# Decisions - infiquetra-agent-plugins

## 2026-10-07

### Setup keeps the machine record out of the repository, and a run does not ask setup questions

**Decision.** Issue #150 (card C3). The machine record is `<home>/.saga/machine.json`, schema `machine_record.v1`, directory mode 0700, file mode 0600. It is not under `.claude/saga/runs`. `survey` sets `ran` and does not clear `offered`. `record_offer` sets `offered` and does not set `ran`. Admission and card C14 both call `record_offer`.

Writing a probed version into `review_tools.pins` while `review-tools.yaml` says `not-recorded` makes `may-block` report-only for the lenses that tool serves. This card accepts that. It does not edit `review-calibration.json`.

The live sandbox probe takes `model` and `effort` from `plugins/saga/references/targeted-reviewer-launch.json` (vendor `claude`, model `opus`, effort `high`). `--probe-sandbox-model` overrides the model. A missing file, a vendor other than `claude`, an import failure, or a non-zero probe is unavailable with reason `probe-unavailable`. Admission does not start the probe.

Nothing is installed, and no optional step runs, unless the operator names it. `install --tools` runs install vectors. `step --name` runs one registry step. The registry is `plugins/saga/references/setup-extensions.yaml`, schema `setup_extensions.v1`, committed with empty `steps` and empty `questions`. A question whose `profile_key` is a known profile key is refused when the registry is loaded.

**Rationale.** The machine is not a repository, so its record does not belong in a commit or in one checkout's run store. A run that stops to ask which tools to install would hide a missing tool inside a question nobody recorded. Naming the tool and `/saga:setup` once is enough. Saga-owned rows share binaries with baseline commands (`git`, `uv`, `python3`); skipping `catalogue: false` keeps those commands unclaimed. The report-only consequence of a recorded pin is the calibration rule already shipped, and changing it here would decide which lenses may block.

**Rejected alternatives.** A fifth probe status for timeouts. Putting the machine record under `.claude/saga/runs`. Adding a setup question to admission. Importing `jsonschema` in the setup script. Letting saga-owned rows match catalogue commands. Editing `review-calibration.json` so a probed pin would not be report-only.

**Revisit when.** Card C14 adds the pane's first-session offer, card C5 adds a repository question, or card C16 adds a step.
### The scripted checks run from the plugin script

**Decision.** Issue #155 (card C5b). `plugins/saga/scripts/review_checks.py` is the plugin's copy. The runner passes the base profile's test commands as one JSON argument and does not read `.saga-profile.json` from the commit under review. The two testing rows set `excused_by` to `test-passes-before-change` and `test-skipped-in-ci`. Machine-specific hits are where-to-look items with no answer. A confirmed finding on `architecture-maintainability.machine-specific-value` stays fix later. When the relocated command fails, the block stays on `architecture-maintainability.relocated-run-fails`.

**Rationale.** The commit under review is untrusted, so it cannot choose the checks, the commands, or the user and host. The two testing rows shipped with no excuse kind, so a builder reason could not clear them. Card C1 did not encode a modifier that raises the machine-specific row when the relocated run fails, and this card does not add one.

**Rejected alternatives.** One shared testing-gap excuse kind. Reading the head commit's profile for the test command. A formula modifier that changes the machine-specific finding's own severity. A new row in `review-tools.yaml`, which the build loop would list as uncovered.

**Revisit when.** A later card adds that severity modifier, or a lister for a language other than pytest, cargo, and swift.

### may-block reads the installed saga, and the profile is the base commit's

**Decision.** Issue #149 repair, after the code review of the calibration file. `may-block` reads the calibration file and the component bytes from the saga directory that contains the script (`parents[1]`). A marketplace install's root is that directory, so `parents[3]` is not a checkout. A path under `plugins/saga/` is read at `<package>/<rest>`. The repository check still hashes `<repository>/<path>`. `--root` and `--profile` select the base commit's profile and do not select the calibration file. The component list adds the three `sweep_pieces.SWEEP_COMPONENTS` paths as literals. A component is a file. An unreadable profile exits 2.

**Rationale.** From the installed plugin, every `plugins/saga/...` path was missing, so a recorded run could never answer `yes cleared`. Pointing `--root` at the reviewed head makes those paths missing too, and a missing component forces report-only, which turns blocking off. C4a's test searches this file for its five path strings. C6's test reads the path sequences this module defines. Both are satisfied by literals in `COMPONENTS`. Importing `sweep_pieces` at module scope would load PyYAML on the repository-check path.

**Rejected alternatives.** Keeping `parents[3]` as the default root. Importing the sweep tuple. Hashing the Semgrep rules directory. Adding `reviewer_answer.py` to the fingerprint in this repair. A read-back of `reviewer_configuration`, which the review command owns.

**Revisit when.** The review command passes the base profile, or the Semgrep rules card lists files instead of a directory.
### Review-tool settings come from the base commit and the plugin

**Decision.** Issue #152 (card C4b). The Python, CloudFormation and CDK, shell, GitHub workflow, and Markdown adapters run at the pins in `plugins/saga/references/review-tools.yaml`: ruff and ruff format `0.15.18`, mypy `2.1.0`, bandit `1.9.4`, coverage `7.16.2`, cosmic-ray `8.7.0`, pytest-randomly `5.0.0`, pytest-socket `0.8.1`, vulture `2.16`, import-linter `2.15`, pip-audit `2.10.1`, checkov `3.3.25`, cfn-lint `1.57.2`, ShellCheck `0.11.0`, shfmt `3.14.1`, actionlint `1.7.12`, zizmor `1.30.1`, lychee `0.24.2`, markdownlint-cli2 `0.23.3`, cspell `10.3.6`, cdk-nag `3.0.2`. A dictionary, a mypy config, or an import-linter contract is taken from the base commit and written under the runner home. ruff selects every rule, isolated, and ignores `noqa`. ShellCheck and bandit do not honor inline silences; a changed line that contains `noqa`, `nosec`, or `shellcheck disable` is recorded and the file is not rewritten. cdk synth, checkov on a synthesized template, cosmic-ray, pytest-randomly, pytest-socket, and zizmor use the relocated allow-list. zizmor stays offline and receives no GitHub token. A cdk-nag synth with no report is a known gap. The two formatters are not started.

**Rationale.** The commit under review can otherwise point a tool at a config that hides the finding. The pins are the context-library Python toolchain numbers where those exist, and the release checked on 2026-10-07 for the rest. import-linter's version line prints `2.15`, so the pin is that token.

**Rejected alternatives.** Selecting only the drafted ruff families. Treating a comment that mentions cdk-nag as proof the aspect is applied. Passing the operator environment into a synth or a test command. Creating `review_calibration.py` in this card.

**Revisit when.** Card C7 reviews the ruff family draft, the actionlint kind draft, and the curated Checkov ids, or a later card puts a sandbox around `cdk synth` beyond the allow-list.
### Review adapters take settings only from the base commit and the plugin

**Decision.** Issue #153 (card C4c of the saga review redesign). The 35 TypeScript, Dart, Rust and Swift rows run on C4a's runner with one rule: the head tree's tool settings are removed before the scan, and base-commit copies are staged back only for the settings each adapter names. A tool whose settings cannot be staged gets a CLI flag instead (clippy `-W`/`-D`), a staged generated file (tsc's extending config, SwiftLint's empty default, cargo-deny's empty config), or a generated core rule set (Dart). Inline suppressions (`eslint-disable`, `swiftlint:disable`, `ts-nocheck`) are degraded notes; the findings still stand. Muter gates on platform inside `invoke`, after the markers check, so a tree without Swift stays silent on Linux instead of recording a platform gap. The version matcher accepts a bare integer only when it is the whole probe output, because Muter tags its releases `16`, `15` and prints the bare number (`Sources/muterCore/version.swift`). `FINGERPRINT_COMPONENTS` grows by the four adapter modules; the yaml rides its own hash. The saga suite refuses sockets suite-wide. `review-tools.md` carries the level maps, rating bands, coverage templates, concurrency lists and gaps in one checked fence: the docs test parses the fence and fails when any value differs from the yaml, the modules or the formula.

**Rationale.** The head commit is untrusted, and a tool config is code the change controls: trusting it lets a change disarm its own review. Staging base copies keeps project settings (which the base commit pins) without trusting head. Muter's platform gate cannot live in `platforms`, because the runner checks that before markers and would gap every non-Swift tree on Linux. The bare-version fallback cannot be a bare number anywhere in the output, because that would read build counts as versions; whole-output-only keeps every dotted match unchanged. The fence exists because prose level tables drift; the npm severities and deny bands live in code, not the yaml, so the test compares the fence against the code.

**Rejected alternatives.** Trusting head configs with a denylist of dangerous keys, which a change can spell around. A `platforms: [darwin]` gate on Muter, which fires on trees without Swift. Pinning Muter to a dotted version it never prints, which degrades every Muter finding to fix-later through the formula's degraded cap. Moving the npm and deny rating maps into the yaml, which restructures working code and a C1-owned formula function for a docs unit. Keyword-presence docs tests, which pass while the values rot.

**Revisit when.** A tool needs a setting the base commit cannot supply (then the strip list, not the trust rule, changes), Muter tags a dotted release, or C2's calibration file lands and takes the extended tuple.

### The targeted reviewer's sandbox blocks the home directory and allows back what the review needs

**Decision.** Issue #189, a follow-up to #158 (card C8 of the saga review redesign, parent #147). `reviewer_claude_settings` in `plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py` now writes `sandbox.filesystem.denyRead: ["~"]` and an `allowRead` holding only three kinds of path:
- the scratch copy;
- the review packet;
- the `bin`, `lib` and (for a virtual environment) `pyvenv.cfg` of each toolchain install under home that `python3` or `node` on the session's `PATH` resolves to. The install's own directory is never allowed back whole, because a tool's home can keep its `.env` beside `bin/`.

A candidate path is dropped, or for the copy and packet the launch is refused, when the path, as written or resolved, is home or above it, is a shared root (`~/.config`, `~/.local`, `~/.local/share`, `~/.cache`, `~/Library`), or is equal to, inside or above a credential path. The launch result lists every allowed path with its reason under `sandbox_reads`. Sandboxed commands receive only the variables on `REVIEWER_ENVIRONMENT_ALLOWED`; every other launch-environment name is denied through `credentials.envVars`, and a credential-looking name is denied even if added to the list. The session's environment sets `GIT_CONFIG_GLOBAL=/dev/null`. Saga's `reviewer_answer.py` replaces known secret formats and long high-entropy runs with `[scrubbed:<kind>]` in every free-text string a record stores (each finding's statement, dispute text, location and proof, and each cleared item's reason) before it builds the record or Jev's state.

**Rationale.** A deny list never covers credential files with arbitrary names, such as a vault password file or an `.env` of provider keys. Blocking the parent and allowing back named paths covers them by construction, and Claude Code 2.1.292 supports it (see LEARNINGS, same date). An environment filtered by name passes a secret held in an ordinarily named variable. Git fails outright when its global configuration is unreadable, so it is pointed at `/dev/null`. The scrubber names the kind, which fleet-core's transport redaction does not, and it protects the record, which that redaction never sees.

**Rejected alternatives.** Adding the missing credential paths to `denyRead`, which the card forbids. A fixed list of toolchain directories, which names one machine's layout. Allowing back the whole toolchain prefix, which a commit security review on 2026-10-07 showed re-opens a file such as `~/.sometool/.env` when `node` sits at `~/.sometool/bin/node`. Allowing back `~/.gitconfig`, which can carry tokens in `url.<base>.insteadOf` rewrites. Allowing every `LC_*` name, which would pass `LC_TOKEN`. Calling fleet-core's `redact_text` for the record, which needs fleet-core loaded on the `--no-jev` path and writes an anonymous placeholder.

**Revisit when.** A Claude Code release changes how `allowRead` works inside a denied parent (`reviewer-probe` checks it live), a second vendor gets a reviewer recipe, or the follow-up on Claude's Read tool lands. That follow-up is needed because, with the operator's user settings loaded, the Read tool read a home canary that the same settings without user settings denied.

### The Jev sweep may send a changed function, a changed block, or a small file

**Decision.** Issue #156 (card C6 of the saga review redesign). After redaction, `jev sweep` may send the changed function, the changed block with 20 lines on each side, and a whole file of at most 400 lines. It returns at most 30 items and stops at $1. It only points. It does not block, clear, or grade. A failed classifier returns no items and a degraded mark, and the review continues.

**Rationale.** The previous data rule allowed diffs and findings, not a whole function or a small file. The sweep's question is about the changed code, and the client's `prepare_state` is the only path that builds a request. The caps keep one review from sending an unbounded tree or spending without a stop.

**Rejected alternatives.** Sending an unbounded file. Sending code through any path other than `typesafe_client.ask`. Treating the sweep as a gate.

**Revisit when.** A corpus run shows 400 lines is the wrong size, or a second classifier replaces Jev.

## 2026-10-06

### The commit under review is untrusted

**Decision.** Issue #188. The commit under review is untrusted. The runner reads pins, rules, the test command, and `coverage_report` from `.saga-profile.json` on the base commit. It scans one detached worktree of the head commit and does not run that commit's hooks or Git LFS smudge filters. Settings files in the worktree are removed and recorded. A relative Semgrep rule path from the base profile is read from a base worktree that stays open until that adapter's scans finish. A changed line containing `jscpd:ignore` or `lizard forgives` is a degraded input, and the file is not rewritten. Coverage is read only from the relocated command's directory. The relocated environment is an allow-list, and the test command must start from a binary on `PATH`. The base cache names the resolved base commit and is not written when the base scan prints nothing.

**Rationale.** A change can otherwise delete a flagged line in the checkout, replace the test command, point Semgrep at its own rules, or reuse a cache entry from before the base branch moved. A rule path resolved inside a worktree that then closes is a path to a deleted directory, so the pinned rules never run. Silence comments hide duplication and complexity findings the same way `gitleaks:allow` hides a secret, and recording them does not change the diff.

**Rejected alternatives.** Scanning the checkout when `git status` is clean. Falling back to the head profile when the base commit has none. Rewriting the relocated command against the checkout. Linking the checkout's dependency directories into the head worktree so a relative `.venv` keeps working. Recording a `package.json` `jscpd` key in this card. Extending `FINGERPRINT_COMPONENTS` with the gitleaks config.

**Revisit when.** The card that runs this runner from the review command. That card has to start the installed plugin, or the plugin at the base commit.
### The calibration file stores verdicts, and one saga function fingerprints the review

**Decision.** Issue #149 (card C2 of the saga review redesign, parent #147). Five choices. "No run yet" is the identifier `no-run` on `corpus_run`; only `recorded` is a run, and any other spelling is a format error. `may-block` answers from the stored verdict, the drift line, the fingerprint and the profile pins. It does not compare the stored numbers with the pass marks. The component list committed here is ten repo-relative paths, written as string literals: C1's formula and record schema, C4a's five `FINGERPRINT_COMPONENTS`, and C8's prompt, answer schema and launch settings. The Semgrep pack is not hashed as a directory and is not committed. `review-tools.yaml` is on the list, so the sha256 already stored beside the pin is what a pack change moves. `review_calibration.py` imports only the standard library at module scope. It imports `review_tools` (and therefore PyYAML) only inside the pin comparison, and it passes that call the tool list under the root being asked about. `scripts/check_repo.py` imports the module inside the check function and does not import PyYAML.

**Rationale.** A typo in the run flag must not disable the gate. Recomputing clearance in saga would be a second copy of the marks and could disagree with the harness. C4a and C8 landed first, and C4a's text search fails if this file exists without those five paths. The Semgrep Rules License forbids shipping the pack. The repository check has to stay runnable where PyYAML is not installed, and an overridden root has to be compared with that root's defaults.

**Rejected alternatives.** JSON `null`, or a missing key, meaning no run. Recomputing the marks in `may-block`. Fingerprinting only C1's two paths. Importing C4a's tuple so the path strings are not in this file. Hashing the operator's Semgrep cache. A top-level `import yaml`. Calling `load_tool_list` with no path.

**Revisit when.** The Semgrep rules license allows shipping the pack, or a real Langfuse run id or Jev model version falls outside the identifier pattern.

### The review tool list is the check map, and the runner does not copy a checkout

**Decision.** Issue #151 (card C4a of the saga review redesign). Five choices. The check map is `plugins/saga/references/review-tools.yaml`: a baseline command answers the row whose binary it names, several rows that share a binary are joined in sorted order, and rows with no binary are not baseline checks. The profile's `mechanical_tool_baseline` commands still run and still decide green. Item 6 is row ids (`tool-error`, `tool-warning`, `tool-style`, `tool-curated`, `tool-unscoped`, plus the medium-low dependency and workflow rows), not a new field on the finding. The relocated test changes its working directory and its home directory and does not copy the checkout; each named language command runs once. Semgrep's rule pack is not committed. The pin is a sha256, the cache is under the user's home, metrics are off, and a missing cache is a degraded input rather than a download. `FINGERPRINT_COMPONENTS` names this card's five paths. This card does not create the calibration file.

**Rationale.** The build loop was carrying a second copy of a catalogue it does not own, and the commands a repository already runs are what decide green. A copied checkout on every unit would duplicate a search a later card owns. The Semgrep Rules License v1.0 forbids shipping the pack. The fingerprint has to exist before the calibration file does, or the later card has nothing to include.

**Rejected alternatives.** Keep reading the lifecycle `mechanical_checks` map, and rename the iteration key. Put a level or the advisory ids on the finding. Copy the tree for the relocated run. Vendor the Semgrep pack. Create the calibration file in this card.

**Revisit when.** The Semgrep rules license allows redistribution, and then the cache can be shipped instead of hashed. Also when the calibration file exists, and then the component tuple belongs in that file.
### The targeted reviewer runs headless on Claude's command sandbox, and other vendors wait for a recipe

**Decision.** Issue #158 (card C8 of the saga review redesign, parent #147). Agent-launcher's new `launcher.py review` starts saga's targeted reviewer headless, never in a Herdr pane. For Claude it runs `claude -p --permission-mode dontAsk --settings <file> --output-format json --no-session-persistence`, with the copy as the working directory and the wrapper plus saga's prompt on standard input. The per-launch settings turn on the command sandbox and fail closed. They deny writes to the system temp roots, reads of credential paths, every network host (`strictAllowlist`) and credential-named variables (`credentials.envVars`), deny `WebFetch`, `WebSearch` and every MCP tool, and allow Bash, edits in the copy and reads of the packet. The scratch copy is `git archive <head>` with no `.git`, under the user's cache directory rather than a temp root. It is written from git's object store rather than `git archive`, so the change's `.gitattributes` cannot shape it. Before launch it withholds what the untrusted change could use outside the sandbox: every `.claude/` directory and `.mcp.json` at any depth (Claude runs their hooks, `apiKeyHelper`, skills' and agents' hooks and MCP servers outside the command sandbox), symlinks leaving the copy, and instruction files at any depth whose possible `@` imports leave it: any `@` token that is not a plain relative path (it holds `..`, `~`, `$`, a backslash, a leading `/` or a non-ASCII character) withholds the file, so no reading of where the token ends can escape. Names are compared case-insensitively, a head whose paths differ only by case or name `.git` in any case is refused, and no export write passes through a symlink. The launch refuses when user or managed settings would widen the sandbox, because list keys merge past `--settings`. API-key variables are removed from the session's environment. The caller passes saga's prompt by path (`reviewer_answer.py paths`). Only `claude` has a recipe; every other vendor is refused by name.

**Rationale.** Real reviews run with instruction files, plugins and hooks, so the reviewer must too, which rules out `--bare`, `--safe-mode`, `--restricted` and a narrowed `--setting-sources`. The sandbox is what keeps the model-written tests from touching anything real, and each setting answers a measured gap (see LEARNINGS, same date). A copy with no `.git` cannot be committed to, and the sandbox stops writes to the real checkout and the network, so nothing can push. A sibling-path lookup for saga works in a catalog checkout but not in a marketplace install. Codex's `workspace-write` sandbox read a file outside its workspace when probed, so it cannot keep credentials from a test; staffing only a vendor whose recipe passes `reviewer-probe` keeps the card's stop condition from firing.

**Rejected alternatives.** A `--headless` mode on `launch`. `git worktree add`, which shares the original repository's `.git`. Copying the working tree, which can hold uncommitted secrets. `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`, which also scrubs hooks' and MCP servers' environments. Unverified recipes for the other six vendors.

**Revisit when.** Another vendor's sandbox can deny credential reads and passes `reviewer-probe` (C9's high-risk second reviewer needs one), or a Claude Code release changes `-p`, `--settings`, the sandbox keys or what `dontAsk` denies.

### Saga's review records: computed severity, a line-free identity, and storage in existing keys

**Decision.** Issue #148 (card C1 of the saga review redesign, parent #147). Three load-bearing choices. First, a severity is never handed in: a finding arrives without one, `review_formula.py` computes it with the row and modifiers that produced it, and validating a stored review run recomputes every severity from the inputs the run embeds and refuses a difference. Second, a finding's identity is a SHA-256 of lens, row, rule reference, file, function and the stored anchor text, with no line number. Third, review runs are appended to the run record's `review_cycles` with `loop: "review_run"`, and builder records are a unit-row key, `builder_record`; no new top-level key.

**Rationale.** A reviewer-written severity is what the redesign replaces, and a stored severity a hand edit could change would reintroduce it. Today's identity (path, line and category, `review_result.py:183`) changes whenever lines move, so a repair round could not tell an unchanged blocking item from a new one. `run_record.TOP_LEVEL_KEYS` is frozen on purpose and mirrored by the Claude mod contract test and orchestrate's fixture copy; using existing keys costs one constant in orchestrate (`DOCUMENTED_FOREIGN_ROW_KEYS`) and one count in `saga_spore.py`.

**Rejected alternatives.** Trusting a stored severity. Storing none and making every reader rerun the formula. An ordinal within the function as the identity (it shifts when a finding is inserted above). A new `reviews` top-level key. A vendored JSON Schema library; the validator is standard-library Python held to the schema file by a test.

**Revisit when.** Card C10b deletes the `review_result.v2` entries; then review runs could move out of `review_cycles`.

### This catalog's saga profile declares a local functional-test environment and no deploy destination

**Decision.** `.saga-profile.json` at the repository root declares `functional_test_environment` with kind `local`, scope `private`, and test command `python3 -m pytest plugins/*/tests -q --import-mode=importlib`. `nonproduction_destination` is `none`. `main_consumed_directly` is true. `concurrency_allocation` is 10. The mechanical baseline is `python3 scripts/check_repo.py`, `python3 -m unittest discover -s tests -v`, that same pytest command, and `git diff --check`. The `qa` block requires `cli-smoke` of `python3 scripts/check_repo.py`, with a ceiling of 180 seconds and no direct cost.

**Rationale.** Issue #114. The three live-profile tests skip until this file exists, and they require the whole profile. The plugin test suite is the test command the card names, and it is the command the `plugin-tests` job runs. This catalog does not deploy. Installed clients load it from this repository's marketplace on `main`, so a merge to `main` is consumed directly. The `qa` block is the smallest schema-valid block whose required strategy this catalog can run: `installed-surface` looks for a marketplace named `infiquetra-plugins`.

**Rejected alternatives.** A waiver. A deploy destination. `main_consumed_directly` false, copied from the profile contract's example for a different repository. The Claude Code matrix job on the mechanical baseline. `installed-surface` in the `qa` block.

**Revisit when.** This catalog gains a non-production deploy, or `installed-surface` resolves the `infiquetra-agent-plugins` marketplace.

### Stack a Markdown table that does not fit the terminal pane

**Decision.** Stack tables that do not fit, measured conservatively, on the terminal only. The saga plan viewer and the review findings pane do this before handing text to `Markdown`. A table at or under the pane's `bodyColumns` is drawn as written. Desktop, VS Code and mobile are unchanged, and the plan file is unchanged.

**Rationale.** The engine lays a table in a pane out for the terminal's width. Pinning a `Box` to the pane width does not change that. Stacking is the rewrite the mod can do, and counting markup in the width means a table judged to fit is never wider on screen than the count.

**Rejected alternatives.** The `Box` width wrapper (it has no effect), a grid of our own, always stacking, and a custom Markdown renderer.

**Revisit when.** The engine lays out pane tables at `bodyColumns`.

### Muse staffs as muse-spark-1.3-contributor and keeps max effort

**Decision.** Fleet Core's staffing palette (`plugins/fleet-core/scripts/fleet_commons/staffing.json`
and its bundled copies in saga and mission-control) maps every Muse tier to
`muse-spark-1.3-contributor`, and Muse accepts `max` with no collapse to `xhigh`. The operator's
favourites file, `~/.config/orchestrate/models.json`, names the same model.

**Rationale.** The operator chose this model for the #147 program on 6 October 2026, and that program
runs Muse at `max` (`docs/plans/2026-10-06-saga-review-redesign-program-plan.md`, decisions D2 and D3).
Muse Code 1.4.3 lists `max` among its efforts (`muse --help`), and `muse model-profile show
muse-spark-1.3-contributor --effort max` reports a measured tuning cell for it. The palette's old
`max` to `xhigh` collapse dated from 13 August, when Muse ran through OpenCode, whose picker offered no
higher rung; left in place, it would quietly lower every saga-staffed Muse role.

**Rejected alternatives.** Keep `muse-spark-1.2-contributor` in the palette and set the model per launch:
saga's own staffing would then disagree with every run the operator starts. Accept `ultra` as well: no
evidence yet that it does better, and it costs more of Muse's allowance.

**Revisit when.** The #147 pilot or the reviewer bake-off shows Muse stopping on usage limits at
`max`, or a newer Muse model is released.

## 2026-10-05

### Saga's code review becomes mostly deterministic, and a lens blocks only after a corpus measures it

**Decision.** The plan in `docs/brainstorms/2026-10-05-saga-review-redesign/plan.md` replaces
saga's lens-roster code review; issue #147 and its children on the Operations board build it. Tools
and our own pattern checks produce findings, and a sweep of narrow Jev (TypeSafe's classifier)
questions says where to look. One targeted LLM (large language model) reviewer answers every
where-to-look item; on high and very-high risk cards a second one, blind to the first, does too. An
LLM finding blocks only when the review command's own sandboxed re-run of its test fails. A fixed
formula grades each lens A to F, and merge needs every lens at C or better. Rounds stop when every
lens is at C or better, when a repair round leaves the same blocking items, or at round 3. Each lens only
reports until a private corpus of known defects and clean changes (`infiquetra/saga-review-corpus`)
shows it clears fixed pass marks: security, for example, must block at least 9 of 10 known blocking
defects and at most 1 of 10 clean changes. Reproduced data loss or a reproduced security exposure
blocks regardless. The reviewer runs with its normal configuration (instruction files, plugins,
hooks) and the subscription sign-in, from any vendor agent-launcher staffs, the same way in real
reviews and in the corpus harness. Every review is traced to Langfuse with what later happened to
its findings.

**Rationale.** A round ran one reviewer session per selected lens, 4 to 15 of them, each re-reading
the whole branch, and was accepted only when every selected lens had a scorer qualified in the
lifecycle repository's executor ledger. That ledger is empty on purpose, so rounds ended
`review_incomplete` (`plugins/saga/scripts/review_consensus.py:2213-2221` at 1f7137d). The spend
bought few decisions, and nothing measured whether a lens caught what it claimed to.

**Rejected alternatives.** Tune the lens roster and consensus scoring: the cost grows with lens
sessions and the ledger gate stays unmet. Measure the reviewer in safe mode or bare mode for
repeatable runs: real reviews always load instruction files and plugins and may move to another
vendor, so a stripped reviewer is a different agent (bare mode also needs a billed API key); the
harness instead turns a component off only where a comparison shows it does not change results.
Split history cases between the tuning and held-out halves by hash: that doubles the history
defects to prove, so history goes to the held-out half only and public sets and planted defects
fill tuning. Let Jev decide when rounds stop: a formula is cheaper and can be audited.

**Revisit when.** A lens cannot clear its pass marks after its questions and tools are tuned on the
corpus; a different vendor becomes the usual reviewer; or Langfuse outcomes show blocked findings
later judged wrong more often than the pass marks allow.

## 2026-10-04

### Claude Code installs this catalog from the GitHub repository, not the local checkout

**Decision.** `scripts/install_client.py` registers Claude Code's `infiquetra-agent-plugins`
marketplace with `claude plugin marketplace add infiquetra/infiquetra-agent-plugins`, which Claude
Code 2.1.289 records as `{"source": "github", "repo": "infiquetra/infiquetra-agent-plugins"}`.
`registration_is_catalog` decides whether an existing registration is this catalog: a `github`
source naming this repository, a `git` or `url` source with this repository's https or ssh URL, or
a `directory` source that resolves to this checkout. `plan_claude` skips the add for any of those,
and `check_claude` reports an enabled install under any of them as `installed-from-catalog`.

**Rationale.** A directory registration makes the installed plugins follow whatever the checkout
holds. On 2026-10-04 the operator's checkout was one commit behind after a release, so the installed
plugins missed the release; a checked-out branch or uncommitted work would leak in the same way.
The operator switched this machine's registration to GitHub by hand, after which `--check`
reported every Claude package as `absent`, because it recognised only a directory registration.

**Rejected alternatives.** Keep the checkout and pull it automatically: branch checkouts and
uncommitted work still leak into the installed plugins. Install from a release tag: the repository
has no release tags.

**Revisit when.** The repository becomes private (a GitHub source then needs credentials on every
machine), or plugin development needs the installed copy to track unmerged work.

### The client assessment drops Gemini CLI from 2026-10-04, and earlier records keep their roster

**Decision.** Agy replaced Gemini CLI on the operator's machine, so `scripts/assess_clients.py`
assesses nine clients from 2026-10-04: Claude Code, OpenAI Codex, Cursor Agent, Qwen, Grok,
OpenCode, Muse, Agy and Hermes. `scripts/check_compatibility_matrix.py` chooses the roster a record
must cover from the record's own required `assessed_on` date: `CANONICAL_CLIENTS` (nine) from
2026-10-04, `CANONICAL_CLIENTS_BEFORE_2026_10_04` (ten, with Gemini CLI) before. A record made
earlier stays valid against the roster in force when it was made, until its package's version moves
and forces a fresh nine-client record. `schemas/compatibility-matrix.schema.json` keeps
`Gemini CLI` as an allowed client name and accepts nine or ten rows; the date rule lives in the
checker. `scripts/install_client.py` keeps its Gemini CLI placement, because that is installation
on a machine that may still have the binary, not assessment.

**Rationale.** Twelve current records, all made on 2026-09-22, honestly assessed ten clients.
Their packages have not changed version, so a fresh run would restate what they already say about
nine clients and drop the tenth. `assessed_on` was already required by the schema and present on
every record, so reading it needs no new field and keeps the schema closed.

**Rejected alternatives.** Re-running all twelve packages now: hours of client runs, and no
information gain for packages that have not changed. Deleting Gemini CLI from the schema: it would
invalidate honest historical records. Adding a roster field to the record: a new field to keep in
step, when the date already decides it.

**Revisit when.** A client is added or removed again, or every current record has been re-run under
the nine-client roster; then the date rule and the ten-client constant can go.

### A shared-environment lease belongs to one invocation, and nothing takes it over

**Decision.** A lease on a shared non-production environment belongs to exactly one
`build_loop.py --combined` invocation, named by an `invocation` nonce written into the holder when
it is taken. No invocation takes over a lease it does not hold: not another run's, and not one
left by an earlier invocation of the same run (issues #139 and #140, follow-ups to #99). The
same-run re-acquire path (`LeaseHolder.left_by_earlier_pass_of` and the `re-acquired` status) is
removed. A crashed invocation's lease is reported `STALE` and released by the operator with
`environment_lease.py release --expect <object id>`. The pass number and start time a lease
carries are read when it is won, not before the wait.

**Rationale.** Replacement keyed on a lower pass number assumed the run record hands out the next
number only after the earlier pass finished. Any other invocation of the run that records a pass,
for example one that gives up after `--lease-wait`, moves the count while the holder is still
deploying, so two deploys of one run could reach the shared stack at once. Only the operator can
know that a holder is dead, and the stale report already gives them the exact command.

**Rejected alternatives.** Re-reading the record before replacing and replacing only when a landed
pass carries the holder's token (#139 and #140's suggestion): a pass lands its record after its
release, so a token in a landed pass means the lease was already released; the only holder it
would replace is one whose release failed, a case rare enough that the operator path covers it,
and the check adds a record read inside the lease protocol. Keeping replacement for the same host
only: two invocations on one host are exactly the failing case.

**Revisit when.** Stale leases from crashed invocations need operator release often enough to cost
real time; then add a liveness signal (a heartbeat on the holder) rather than inference from the
record.
### Code review starts from a gate command, and the cycle cap is refused at the record

**Decision.** Two checks enforce issue #91's operator rulings 4 and 5 (issue #100, pre-review
testing U5). First, `/work` §5.1 and a standalone `/code-review` Phase 0.3 take the revision to
review only from `build_loop.py --handoff`, which exits 0 and prints it only when the latest
combined-branch pass at that revision is green or waived, and refuses with exit 2 otherwise.
Second, `review_result.append_result`, the one write path for both `/work` and a standalone
review, refuses a `code_review` entry with the outcome `cycle_cap_best_available` at a revision
without that evidence. `release_step.py close` then cites the evidence, or the waiver and its
reason, and refuses a `delivered` close when a cap revision is unproven or the cap left more open
findings than residual issues filed. `build_loop.functional_evidence` now lets the latest pass at
a revision decide, so a later failing pass withdraws an earlier green one.

**Rationale.** The hand-off was prose (`/work` read `units[0]` with inline Python), so nothing
could test it; a command with an exit code can be tested and cannot be skipped by mis-reading the
record. The write path is the single place both callers go through, and refusing there keeps the
verdict computed by `review_consensus.py` unchanged: code review still decides nothing about
acceptance, which was this card's stop condition.

**Rejected alternatives.** `/code-review` refusing to score an unproven revision at the cap: that
makes the review decide acceptance. A Work-only prose check at §5.3: untestable and easy to
bypass. Letting `--review-gate-override` cover the functional gate: it is an acceptance override,
and the recorded waiver, whose reason the closeout prints, is the only exception ruling 2 allows.
Adding the evidence to `CLOSEOUT_PARTS`: that tuple mirrors infiquetra-sdlc's
`terminal-outcomes.md`, so the two new parts follow it instead.

**Revisit when.** infiquetra-sdlc's `terminal-outcomes.md` names a functional-evidence closeout
part (then move it into `CLOSEOUT_PARTS`), or a run-level waiver lands on the run record and the
gate has to read it.

### An orchestrate expansion creates one `/work` row per plan unit, named by its U-ID

**Decision.** When orchestrate expands a run with its `/work` phase, it creates exactly one row per
plan unit, and names the row by that unit's U-ID (`U1`, `U2`, ...). A lane that builds several plan
units carries several rows, one per U-ID, never one row under a lane name (issue #135, the
follow-up to #98). The portable skill and the Claude `/orchestrate` command state the rule in the
same words, and `plugins/orchestrate/tests/test_orchestrate_authoring_contract.py` fails if either
shows a `/work` row with any other name.

**Rationale.** `plugins/saga/scripts/functional_checks.py write` finds each plan unit's row by its
`id`, `name` or `unit_id`. In an orchestrate-driven run the rows do not exist when `/plan` writes,
so `/work` writes again before its first build-loop iteration and stops on exit 5 if a unit still
has no row. One row per U-ID makes that lookup exact with no change to the writer or to `/work`.

**Rejected alternatives.** Letting `/work` pass the U-IDs a lane builds to the writer and count
exit 5 only for those: it adds a second naming channel the writer and the build loop would both
have to learn, and a lane row still could not carry several units' checks under one key. Leaving
the rule in the skill alone: the Claude command is what an operator actually follows, and its
example taught the opposite.

**Revisit when.** A `/work` lane needs to build several plan units in one session and one worktree
often enough that one row per unit becomes a cost.
### A shared non-production environment is leased through a compare-and-swap push to the git remote

**Decision.** The combined-branch pass (issue #99, pre-review testing U4) holds a shared
environment through the git reference `refs/saga/leases/<name>` on the remote the declaration
names, default `origin` and `shared-nonprod`. `plugins/saga/scripts/environment_lease.py` acquires
it by pushing a commit on the empty tree, whose message is the holder, with
`--force-with-lease=<ref>:` (an empty expected value: only if the reference does not exist) and
`--no-verify`, and releases it by deleting it with `--force-with-lease=<ref>:<oid it acquired>`.
The holder names the repository, issue, revision, a short host label, start time and bound. (The
same-run replacement this entry first allowed was removed the same day; see "A shared-environment
lease belongs to one invocation" above.) Every holder waits like any other; a stale lease is reported with the exact release
command and never broken automatically. The record and the merge turn stay lock-free, as issue 1018
required; this is the one scoped exception, required by issue #91's operator ruling 3.

**Rationale.** The card's stop condition is a lease every deploying host can see. Every such host
already pushes to the repository's remote with the credentials it has, and the push carries the
expected old value, which the server's reference transaction compares, so a create is atomic
across hosts. A local experiment had exactly one winner in 20 of 20 concurrent creates. It needs
no new infrastructure, works with any git host, and the tests drive real git against a bare
repository with no network.

**Rejected alternatives.** A lock file in one checkout (one host only). A GitHub label or issue (no
compare-and-swap). The Deployments API or environments (no atomic acquire outside Actions). Actions
concurrency groups (they serialise workflow runs only). The GitHub refs REST API (atomic, but
GitHub-only and three API calls where one push serves every remote). A DynamoDB or S3 lock (new
infrastructure). A field in the run record (one host's file, and issue 1018's rule for the record
still holds).

**Revisit when.** A deploying host lacks push rights to the remote, a remote rejects the
`refs/saga/` namespace, or the step-10 delivery to a shared stack (the run model's "the hold covers
every deployment to that environment") is built and needs the same lease from `release_step.py`.

### The merge turn moves before code review

**Decision.** `/work` brings the units together in Phase 3.2 and runs the combined-branch loop in
Phase 3.3, before Phase 5's review. §5.4 keeps the release, the deploy, the functional test and the
close. §5.1 reviews the revision in `combined_branch.handed_to_code_review`. Every entry into review,
a repair batch from review or from the post-merge `/qa` loop included, passes the combined loop
first. `merge_turn.integration_state` says when integration is complete.

**Rationale.** The lifecycle's run model at infiquetra-sdlc `e5a2be10` brings work together (step
6) before it reviews it (step 7), and issue #91's rulings 3 and 4 require review of a combined
branch that passed its functional run. Before this, the merge turn ran after review, so review saw
one unit's branch and the integrated branch was never reviewed or functionally tested before
release.

**Rejected alternatives.** Running the combined pass after review (review would judge code nobody
had seen run). Running the deployed check per unit (a shared stack would receive unit branches).

**Revisit when.** Orchestrate-driven runs, whose merge turn lives in orchestrate's own driver, need
the same combined loop.

### Exit 5 is an environment stop, distinct from a refusal and from "not green yet"

**Decision.** `build_loop.py --combined` exits 5 on the third consecutive `could-not-execute`
combined pass and prints the passes' environment problems. A deploy or teardown that exits
non-zero is `could-not-execute` with its exit code kept; a test that exits non-zero is `fail`.
Waiting out a held lease counts toward the streak. The next invocation still runs.

**Rationale.** The card asks for the loop to stop after three environment failures and name the
problem for the operator. Exit 4 means "fix the code and run again", and exit 2 means "bad input";
a caller must be able to tell "the operator has to fix the environment" from both.

**Rejected alternatives.** Reusing exit 2 (a refusal implies the input was wrong). Counting a
failed deploy as a code defect (the card says it is never one; the cost is that a change that
breaks its own deploy reaches the environment stop after three passes, and the baseline that runs
first catches most such breakage).

**Revisit when.** The run model gives environment failures a numeric allowance of its own.

### A plan proves its acceptance criteria in fenced YAML blocks, copied onto the run record by their own script

**Decision.** A plan names each unit's functional checks in a fenced block whose info string is
`functional-checks`, under the unit's `### U<N>.` heading, and the plan-level smoke in one
`scenario-smoke` block under `## Scenario Smoke` (issue #98, pre-review testing U3). Each entry is
`{name, command, proves, runs}`. `proves` cites criteria as `AC-<n>`, the criterion's 1-based
position in the issue's `### Acceptance criteria` list, and `runs` is `local` or `environment`. A
change with no code writes a `functional-test-waiver` block with its reason in place of the smoke.
A new script, `plugins/saga/scripts/functional_checks.py`, reads the blocks once: `write` copies
them onto the run record's unit rows at `/plan` §5.3a under the record lock, `map` is the blocking
check `/doc-review` runs, and `plan_artifact_conformance.py` reports malformed blocks through the
same parser. A unit iteration of the build loop runs only `local` entries; `environment` entries
are recorded and deferred, with the reason `deferred-to-combined-branch`.

**Rationale.** The build loop already read `functional_checks` and `scenario_smoke` from the unit
row, so the writer only had to produce that shape. A fenced YAML block keeps the plan's per-unit
bold-label prose intact under the formatting contract and parses without guessing. Numbering
criteria by position reuses the `AC-<n>` vocabulary `parse_issue.py` already reports, and `map`
quotes each criterion's text so a renumbered issue shows as a mismatch, not a silent pass.
Deferring `environment` entries follows parent ruling 3 of #91: a shared stack only ever receives
the combined branch, and a unit loop that tried to reach an undeployed environment would never go
green.

**Rejected alternatives.** Parsing the checks out of bold-label prose (`**Functional checks:**`
lines), which breaks on every formatting variation. Matching checks to criteria by their text,
which drifts the first time either is reworded. Writing the checks through `saga.py save`,
`plan-save-contract.yaml` and `plan_save_contract.py`, as the card listed: those render and prove
the saga tick, which is untracked local state, while the run record is what the build loop reads.
Running `environment` entries in every unit iteration.

**Revisit when.** Pre-review testing U4 (#99) runs the deferred entries on the combined branch, or
an issue template gives acceptance criteria stable identifiers of their own.

### The run status band's words are rendered by `run_status.py`, not by the mod

**Decision.** The run status band (issue #105) draws `band_line` exactly as
`plugins/saga/scripts/run_status.py summary --json` prints it, one line per active run, for example
`#412 · work · build loop pass 3, 2 failing · review cycle 1/3 · 7/10 lenses met`. The script
computes each part from the run record: the build loop's latest iteration (for the unit whose
`worktree` is this checkout, or the only unit that ran the loop; otherwise "2/3 units green"), the
latest code review cycle against `standard_cycle_allowance` (past it, "4/5 (escalated)" against
standard plus escalated), and lenses met through `lens_views`, which applies
`review_consensus.lens_outcomes_for_result`. `summary --band` prints the same line as the plain
fallback. The keys are additive inside `run_status.v1`, so the version token did not change. The
band says "build loop", the record's term, where the card's example said "test loop".

**Rationale.** Operator ruling 2 on the mods parent (#92): scripts own state and policy, a mod
displays it. Whether a lens met its bar is the verdict's threshold rule; recomputing it in
TypeScript from `run_record.py show` would be a second copy that drifts. One renderer in Python
also gives every other harness the identical line.

**Rejected alternatives.** Re-deriving lens "met", cycle allowances and build-loop counts in the mod
from `run_record.py show` (duplicates policy). A separate `--cwd` flag for matching a unit's
worktree: `--repo-root` already resolves to this checkout's top level, which is what a unit's
`worktree` names. Opening the plan viewer and review pane from the band with `$.command.run`: a
plugin's own call skips its own hooks, so it never reaches `/plan-view` or `/review-view` (see
LEARNINGS.md, same date).

**Revisit when.** The run record stores per-lens "met" itself, or a combined-branch functional
loop (issues #99 and #100) needs its own segment on the line.
### A repository's functional-test environment lives in its tracked saga profile, and admission writes it once

**Decision.** `.saga-profile.json` carries a `functional_test_environment` block (`kind`,
`deploy_command`, `test_command`, `teardown_command`, `scope`) or a `functional_test_waiver` with a
reason (issue #97, pre-review testing U2). It replaces `branch_preview` and
`branch_preview_command` through a read-time migration. When neither is declared, admission asks
one question and, on the operator's answer, writes the block into the tracked profile in the
checkout it ran in, before it saves the run record. The resolved form is recorded at
`admission.functional_test_environment` with `mode` `declared` or `waived` (the shape #98 reads),
and a waiver carries `level: repository` to tell it from the Planner's run-level waiver.

**Rationale.** The lifecycle at infiquetra-sdlc `e5a2be10` (sdlc#174) makes the declaration a
repository fact that the operator supplies once and that is written back so the next run does not
ask. The profile is already tracked and already the home of repository facts. Writing it before
the record means a failed write leaves the question outstanding instead of recorded as answered.
A legacy `branch_preview: true` profile is read as an incomplete declaration and offered as the
question's default, because the old keys said a preview existed, not how to test against it, and
taking them as an answer would be the plugin choosing the mechanism (parent ruling 2 of #91).

**Rejected alternatives.** A separate file under `.saga/`, which is git-ignored, so a fresh worktree
would ask again. Keeping `branch_preview` beside the block, which leaves two answers to one
question. Migrating a legacy preview silently into an `ephemeral-stack` declaration without asking.
Running the declared commands per unit now, which would deploy units to a shared stack and break
parent ruling 3.

**Revisit when.** Pre-review testing U4 (#99) runs the declaration on the combined branch and
retires the per-unit preview, or a second harness needs the declaration outside the saga profile.
### Jev applies a tier raise by itself at 0.8, one step, effort first; lowering stays advisory

**Decision.** Saga staffing's tier judgment (issue #96) is on by default whenever a TypeSafe key is
configured, and `INFIQUETRA_TYPESAFE_TIERING=off` switches it off with no request. It runs once at
admission for every role, given the issue, and once in `/plan`'s tier table for every unit, given
that unit. It asks Jev a narrower question than before: does this unit need a weaker, the same, or
a stronger tier than its default? A raise at confidence 0.8 or above applies automatically, one
step, effort first (one effort rung while the model's ceiling allows it, else one model rung),
never to Fable, never past `xhigh` (coordinator ruling: `xhigh` is reachable, `max` is not on the
palette), and never over a tier an operator or the repository overlay set. It is recorded as
`jev_raise` with a reason composed from the chosen criterion and the confidence, and the staffing
resolver honors it as its `jev-raise` layer. A raise from 0.6 up to 0.8 is pre-filled in admission
question 4 or proposed in `/plan`'s table for the operator. A lower tier is shown as advisory and
never applied. Below 0.6 an answer is logged and not shown. House rule 10 in
`plugins/fleet-core/references/typesafe.md` is amended for raises only. Each verdict is logged
once its label is known: the direction from the default to the tier the operator finally accepted.

**Rationale.** Opus/medium builders cost real money, and the cheaper mistake is an unnecessary
one-step raise, not a silent quality loss. A raise is bounded and visible (one step, a reason, the
operator can still override), whereas a wrong automatic lowering is invisible until review fails.
The one prior tier verdict in the log (2026-09-20) answered `opus/max` at 0.9 from a work-shape
label alone, which is why the question became relative to the default and the step became one
rung. Labels from the operator's answer are what will let the harness decide later whether
lowering may ever be automatic.

**Rejected alternatives.** Asking for an absolute tier from the whole palette (it reached for the
top of the scale). Automatic in both directions (a lowering can only be trusted after measurement).
Staying fully advisory (no run ever used it; no skill passed `--suggest`). Confirming every raise
per run (an extra question on every admission for a bounded, reversible change). Allowing a raise
to Fable or `max`.

**Revisit when.** The harness holds about thirty labeled verdicts per direction; or agreement in
the 0.8-and-above band falls below what justified automation; or issue #95's cost per completed
unit shows automatic raises adding cost without fewer repair cycles.

### The review findings pane shows "unscored" apart from "not run", and takes both from the verdict

**Decision.** `plugins/saga/scripts/run_status.py review` (schema `review_view.v1`) gives each lens
of the latest review result one of four states, and the `/review-view` pane (issue #108) shows them
as they come. `met` and `not_met` are the usable rows; `not_run` is a lens that did not execute or
a selected lens (`run_configuration.applicable_lenses`) with no row in the result; `unscored` is a
lens that ran and reported findings but sets no bar (catalogue-unscorable, or no qualified
executor). The state comes from `review_consensus.lens_outcomes_for_result`, the loop body of
`verdict_for_result` extracted unchanged, so the pane and the verdict apply one rule. Only a
usable lens carries `derived_overall` in the view, and the pane draws no score at all.

**Rationale.** The card's acceptance criterion says a lens with no usable result is labelled "not
run". The verdict has two distinct unusable cases, and an unscored lens did run and may hold real
findings; calling it "not run" would hide those findings behind a label that says there are none.
Both labels meet the criterion's purpose, which is that an unusable lens never reads as a low
score. Operator ruling 2 on the mods parent (#92) keeps the rule in the script; a mod that
recomputed "met" from the thresholds would be a second, driftable copy of the verdict.

**Rejected alternatives.** One "not run" label for every unusable lens (above). Computing the
state in TypeScript from the raw `per_lens_results` rows (a second copy of policy in a mod).
Matching on the reason text in `run_status.py`: the reasons are now named constants in
`review_consensus.py`, which the view maps from.

**Revisit when.** The verdict gains another unusable case, or the executor-verification ledger
gains entries and "unscored" becomes rare enough to fold away.

### Saga mods read a display view from `run_status.py`, not the plan path from the run record

**Decision.** `plugins/saga/scripts/run_status.py summary --json` (schema `run_status.v1`) is the
read-only view the saga mods show (issue #104). It joins the run record (`next_step`,
`updated_at`) with the per-worktree saga envelope (lifecycle phase, plan path) and writes nothing.
The plan viewer pane reads the run's plan path from it; `mods/run-record.ts` holds its argv builder
and parser beside the run-record reader, so every mod's state reading stays in one module. The
text form is the plain fallback other harnesses print. Later display mods (issues #105, #107,
#108) extend this script rather than adding their own.

**Rationale.** Operator ruling 2 on the mods parent (#92): scripts own state, mods display it. The
run record has no plan path, and its twelve top-level keys are frozen (`run_record.TOP_LEVEL_KEYS`),
so the plan path can only come from the envelope. A mod reading envelope files itself would parse
saga's storage format in TypeScript.

**Rejected alternatives.** Adding `plan_path` to the run record: it breaks the frozen key set for a
value the envelope already owns. Calling `saga.py restore` from the mod: it needs the saga id,
which needs the issue, which needs `next_step_context.resolve_issue`; that resolution belongs in
Python, once. Section text that stops at the next heading of any level: a `##` section would then
lose its `###` subsections, so a section runs to the next heading of the same or a higher level
and its subsections are listed again on their own.

**Revisit when.** The run record gains a plan path, or a mod needs a field that changes faster than
a script call every few seconds can serve.

### Orchestrate's launch approval waits in the engine's question dialog, on a table the script prints

**Decision.** Issue #109 moves orchestrate's launch table out of the model's hands.
`orchestrate.py launch-table --plan <file> [--issue <N>]` prints it in one fixed format, validated
by `start`'s checks (or `expand`'s, through the new shared `validate_expansion`), with the plan
file's sha256 in its header, and a golden test in
`plugins/orchestrate/tests/test_orchestrate_launch_table.py` pins the format. In Claude Code the
model calls `mcp__orchestrate__review_launch_table`; the mod in
`plugins/orchestrate/com.infiquetra.claude/mods/launch-approval.tsx` shows that text in a pane
and collects the answer with `$.ui.ask` (the engine's AskUserQuestion dialog), options ordered
Change, Cancel, Approve so a reflexive Enter does not approve. The tool's result is the decision
only; the model still runs `start` itself, so the mod launches nothing. Every other harness prints
the same text verbatim. The plan gains two display-only keys, `vendors_allowed` and
`later_phases`, which `start` and `expand` ignore.

**Rationale.** The card asked for Approve and Change buttons in the pane. A hook's own time is
capped at ten seconds (`HookBudget`, claude-code.d.ts in 2.1.289) and only a wait inside a `$` or
`next` call is free, so a tool call cannot wait on a pane press; `$.ui.ask` is that free wait and
its answer comes back as the tool result, which is the provenance a launch gate needs.

**Rejected alternatives.** Pane buttons that answer through `$.prompt.submit`: the answer would
arrive as a plugin-originated prompt, not as the tool's result. `$.tool.call` of AskUserQuestion:
the host refuses it and points at `$.ui.ask`. Letting `start` refuse a plan whose digest differs
from the approved one: that changes the launch path, which the card keeps out of scope; the
digest is shown and returned so the operator and the model can compare it.

**Also decided.** The plugin's one `session.start` hook lives in `mods/index.ts` and registers the
`/fleet-view` command and the tool from plain-data specs the two mod files export. The fleet pane's
refresh timer is started by the command and cancelled when the pane closes, so nothing polls while
no pane is open.

**Revisit when.** The mod API offers a free wait on a pane press, or `start` gains a digest check
(then pass the approved `plan_sha256` to it).

### Saga's roles become Claude Code agent types registered by a mod, tiered from the run record

**Decision.** In Claude Code, saga's mod registers one agent type per role of the active run
(`saga:worker`, `saga:planner`, `saga:plan-reviewer`, `saga:functional-tester`,
`saga:release-worker`) through `$.agent.register`, with the role's model and effort (issue #106).
`plugins/saga/scripts/role_agent_types.py` decides what to register. Every role's tier comes from
fleet-core's staffing resolver (`staffing.resolve_role`, from the bundle, run from the checkout so
the overlay applies). The script hands the resolver what the run record's
`staffing_models_and_efforts` holds for the role: a row the operator answered goes in as the
operator's answer, and a recorded `jev_raise` goes in as the raise. Which rows the operator
answered is `run_record.operator_answered_roles`, the one rule admission's staffing table also
reads: under a per-role merge only the rows marked `operator_override: true`, under a whole-map
answer every row. The script writes no precedence order of its own; the resolver's one order
(issue #93) decides. Each prompt is the roles-library file, read at call time through agent-launcher's
roster helper, behind a short saga hosting preamble: report the handoff as the final message and
post nothing on the issue. `/work` dispatches a build unit as `saga:worker`, with no `model`
parameter, only when the type's tier equals the unit's resolved tier; otherwise the effort rider
stays the route. The type is named after the staffing role (`saga:worker`), not `saga:builder` as
the card's example had it, so no third spelling joins `worker` and `implementer`. A mod-side
`turn.step` check reports a request that does not carry its type's tier as
`tiering-drift[claude-agent-type]` and never rewrites it. `fleet_commons.effort_rider` gains
`claude-agent-type` as a real-knob spawn kind.

**Rationale.** The Agent tool takes a model per call but no effort, so effort on that path was a
prompt instruction, the labeled proxy. A registered type carries a real effort. Reading the tier
from the resolver, with the record's operator answer and Jev raise as its inputs, keeps the types,
the drift check and `/work`'s unit tier on one answer, including an operator's and a raise's.

**Rejected alternatives.** Static plugin agent files (`agents/saga-worker.md`): Claude Code honors
their `effort:`, but a file cannot carry a per-run tier and would hold a copy of the library prompt
that drifts. Reading the record's row first and the resolver only for gaps: it wrote a second precedence
order, and it registered a role one step below a recorded Jev raise. Calling the
`staffing.py resolve --role` command line: it takes neither an operator answer nor a raise, and it
costs one process per role on every refresh. Running the library prompt verbatim: the implementer prompt tells
the subagent to post handoff comments, which `/work` routes through mission-control instead. A mod
that rewrites the request's model or effort: the mods parent rules that a mod never enforces policy.
A `saga:builder` alias: a third name for one role, with a mapping to keep in sync.

**Revisit when.** The Agent tool gains a per-call effort parameter (then the rider route and the
type route can merge), when measured runs show many build units whose tier differs from their
role's type (then register tier-variant types such as `saga:worker-opus-high`), or when `/plan`,
`/qa` and `/code-review` dispatch their roles directly and should use the types too.
### Admission renders the staffing and lens tables itself, from the same rows as its JSON

**Decision.** `plugins/saga/scripts/admission.py --render tables` prints the operator-facing
staffing table and lens table in one fixed Markdown format, and the plan skill tells the model to
print that block exactly as rendered (issue #102). The Markdown is built only from the rows that
`--render json` (schema `admission_review.v1`) emits, so the plain table every harness prints and
the Claude Code review pane planned in issue #103 cannot disagree. The tables are titled in bold
text, not Markdown headings, because a heading line quoted into a skill would split that skill's
gate-record sections for `lint_gate_absence_contract.py`. A golden constant in
`plugins/saga/tests/test_admission.py` pins the format.

**Rationale.** The questions were already data, but the presentation was left to the model, and
operators kept asking for the staffing layout again as a table because it came out differently
every run. Rendering in the script makes the format a property a test can hold in every harness,
not only Claude Code.

**Rejected alternatives.** Letting the model format the tables from a stricter prompt: the drift
this fixes is that very improvisation. A pane that parses the printed Markdown: the mods foundation
(issue #101) rules that a mod never parses prose, so the pane reads the JSON instead. Markdown
headings as table titles: they break the gate-record lint as described above.

**Interim copies, deliberately.** The Proposed and Why columns apply the staffing precedence of
coordinator ruling 7 (operator answer > repository overlay > a recorded Jev raise > work-shape
default, refusing a raise that is not exactly one step up or that names fable or max) in one
display-only function, `_proposed_and_why`, because the resolver issue #93 builds does not exist
yet. (Issue #93's review replaced that copy: `_proposed_and_why` now hands a recorded raise to
the resolver through `_resolve_one_role` and words the decision's `source` and the resolver's own
refusal message, after the copy was found showing a model-rung raise the resolver had applied as
refused.) Likewise the tier-judgment band names (issue #96) and the 0.8 / 0.6 lens bands (issue #110)
are copied, not imported. The JSON carries a `status` field (`unreachable`,
`catalogue-unreadable`) instead of placeholder rows, so a pane never has to match display text.
The keys the tables read are listed in `plugins/saga/references/run-record.md`.

**Revisit when.** A harness needs a different format than Markdown tables, or the Jev data the
tables read (the per-role tier judgment from issue #96, the lens proposal from issue #110) lands in
a different place in the run record. Replace the remaining interim copies when #96's band
constants and #110's thresholds land: call or import them and delete the copies here. When issue
#96 merges a `staffing_overrides` answer per role, remove the plan skill's "complete role map"
answer rule (SKILL.md §0.1b) and the matching caveat in `references/run-record.md`; the admission
question's own prompt was left unchanged, as the card requires.
### Run records take a lock for every read-modify-write

**Decision.** Issue 95 gives the saga run record (`run_record.v1`) a lock. Every read-modify-write
takes `fcntl.flock(LOCK_EX)` on the sibling `<record>.lock`, re-reads the record while holding it,
applies its change, writes through the existing atomic replace and releases. The lock file is
created when missing and never deleted. `run_record.update` (and `run_record.file_lock` for a
record named by path) is the saga implementation, and every saga writer uses it: the build loop,
review results, admission, the qa block, merge turns, `set_next_step` and `usage add`, plus
agent-launcher's roster writer. A slow writer does its work unlocked and lands only its own keys on
a record re-read under the lock. Orchestrate takes the same convention in issue 113.

**Rationale.** The record was built with no lock on the premise that one coordinator owns one
record. Usage capture breaks the premise: unit sessions write their own `usage` entries while the
coordinator and the build loop write the same file, and a writer that saves a copy it read
earlier silently drops every change made since. `flock` is released by the kernel when the
process dies, so there is nothing to expire, steal or reconcile — the objections issue 1018 had to
leases and reservations do not apply to it.

**Rejected alternatives.** Re-read and compare `updated_at` before the replace, retrying on a
mismatch: it narrows the window but cannot close it, because the compare and the replace are two
steps. A lease or reservation recorded in the file: it needs expiry and recovery, which is what
issue 1018 forbade. One usage file per unit session: it would split the record the run-record
design exists to unify.

**Revisit when.** A writer runs on a filesystem where `flock` is not honoured (a network mount),
or the record moves off the local disk.

### Usage entries accumulate per session; review_incomplete is not a completed unit

**Decision.** A usage entry is identified by session id, role, vendor, model and effort; a repeat
`usage add` adds into it. The price table is YAML with `usd_per_million: null` for a model whose
rates were not verified, and the cost report never prices such a model at zero. A unit counts as
completed only when its build loop is green and its latest code review is `accepted` or
`cycle_cap_best_available`; `review_incomplete` does not count.

**Rationale.** The card asks for one entry per model session, and the live-capture mod will
report a long session as several deltas, so accumulation satisfies both. Each entry records its
own role and tier because no per-unit role exists anywhere else in the record. Counting
`review_incomplete` as completed would make a unit whose review never finished look cheap — the
opposite of what the measurement is for (checking issue 90's Opus builder decision).

**Rejected alternatives.** Append one entry per call: the record grows with every capture tick and
a session's spend has to be summed by every reader. Price an unverified model from a cached table:
a guessed rate looks exactly like a verified one in the output.

**Revisit when.** A vendor reports cost directly in its usage data, or the price table's
`verified_on` passes 30 days (the report warns), or review_incomplete units turn out to be a
material share of spend.
### Claude Code mods live in the Claude adapter, load from Claude Code 2.1.286, and are validated in CI

**Author.** Claude for Jeff Cox (issue #101, mods U0, branch `issue/101-mods-foundation`)

**Decision.** A Claude Code mod is a TypeScript module, and it lives only in a
package's Claude adapter:

- Saga's and orchestrate's modules sit under `com.infiquetra.claude/mods/`.
  Each adapter's `hooks/hooks.json` names one entry module under `modules`
  (`["../mods/index.ts"]`), beside saga's command hooks in the same file.
  Orchestrate had no hooks file, so it gains one holding `modules` and an empty
  `"hooks": {}`, and its Claude packaging manifest gains the `hooks` path. The
  empty object is required, not decoration: see the older-build observation.
- Saga's state contract for mods is `com.infiquetra.claude/types/index.d.ts`,
  named by `"types"` in `plugins/saga/.claude-plugin/plugin.json`. That is a
  path-only change, as the 2026-08-25 decision "Claude installs the package
  root" requires.
- Mods read saga state only by running `run_record.py show <issue>` through
  `$.process.run` and parsing its JSON, and write back only through a script's
  command line. The guarded reader is written once, `readRunRecordWith` in
  `mods/run-record.ts`; a mod passes it `(argv) => $.process.run(argv)`, and it
  turns a run that could not start or timed out into reason `'error'`, so no
  mod carries its own catch.
- One departure from "never parse prose": `run_record.py show` exits 2 both for
  a missing record and for every other loader failure, with no exit code of its
  own for the missing case. The reader tells them apart by the start of the
  script's stderr message (`NO_RECORD_PREFIX`), and
  `plugins/saga/tests/test_mod_run_record_contract.py` pins that prefix and
  both exit codes against the real script. Revisit when `run_record.py` gains
  a distinct exit code for a missing record; the reader then matches the code.
- Loading a package that has a hooks module with `--plugin-dir` makes the
  engine write `<package>/tsconfig.json` (and `.claude-plugin/types/`, which
  carries its own `.gitignore`). The repository `.gitignore` ignores
  `plugins/*/tsconfig.json`, and `scripts/check_repo.py` refuses one that is
  committed anyway, so the Claude-only file never lands in the portable root.
- `scripts/check_repo.py` refuses every suffix the engine loads as a module
  (`.ts .tsx .mts .cts .js .jsx .mjs .cjs`) outside
  `plugins/<package>/com.infiquetra.claude/`. In a git work tree it takes its
  candidates from `git ls-files --cached --others --exclude-standard`, so
  `.gitignore` is the one authority on what could be committed; without git it
  walks the tree, pruning a directory list a test checks against `.gitignore`.
  `node_modules` is not ignored, so a committed dependency directory is checked
  like any other.
- The minimum build is **Claude Code 2.1.286**, held as `CLAUDE_CODE_FLOOR` in
  `tests/test_claude_plugin_packaging.py`. A new `claude-mods` CI job installs
  2.1.286 and 2.1.289 from npm and runs `claude plugin validate --strict` and
  `claude plugin test` on every package whose adapter names a module.

**Why 2.1.286.** The card's rule was "2.1.289 or the first build with mods,
whichever is earlier". Measured on real builds (darwin-arm64 binaries from npm,
2026-10-03 and 2026-10-04), "the first build with mods" has three readings:

- 2.1.242 is the first build that parses `modules`. It loads a module only
  behind a server-side rollout flag (`tengu_plugin_hooks_modules`) that is off by
  default.
- 2.1.246 has no `claude plugin test` and does not know events the mods will
  use (`"session.start" is not an event`).
- 2.1.285, the npm `stable` tag on 2026-10-03, loads an installed plugin's
  module only with `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` and runs `claude plugin
  test` only with it set.
- 2.1.286 is the first build that loads the module by default (debug log:
  `hooks module saga@inline loaded`) and runs `claude plugin test` with no
  environment variable.

The mods ship enabled by default (the #92 operator ruling), so the floor is the
first build where that is true without operator action. Builds below it,
including the stable channel today, get the plain fallbacks every other harness
gets.

**Older-build observation (the card's stop condition did not trigger).** A copy
of saga with this change was loaded with `--plugin-dir` and no network on
2.1.220, 2.1.241, 2.1.242, 2.1.246, 2.1.285, 2.1.286 and 2.1.289. Every build
logged `Registered 8 hooks`, which is all eight of saga's command hooks,
including the PreToolUse gates, and ran the SessionStart hooks. 2.1.220 and
2.1.241 ignore `modules`. 2.1.242 through 2.1.285 log that the module was not
loaded and carry on. On 2.1.289 a module that fails to load (`"no.such.event"
is not an event`) logs `hooks module saga@inline failed to load` and still
registers the eight command hooks. Builds up to 2.1.246 report the manifest's
`types` field as an unknown field they ignore (`claude plugin validate` passes
with that warning); 2.1.285 recognises the field and passes with no warning. So
the module stays in the same hooks file.

Orchestrate's hooks file was checked separately, because it has no command
hooks. Holding only `modules`, it fails to load on 2.1.220 and 2.1.241: the
debug log shows `Failed to load hooks from
./com.infiquetra.claude/hooks/hooks.json for orchestrate` with `"path":
["hooks"], "message": "Invalid input: expected record, received undefined"`,
and the plugin is marked `hook-load-failed`. Its command and skill still load,
but an operator sees a plugin error that orchestrate never had before. Those
builds' `claude plugin validate` does not read the hooks file, so validation
passes and only a real load shows it. With `"hooks": {}` added, 2.1.220,
2.1.241, 2.1.242, 2.1.285, 2.1.286 and 2.1.289 all load the file with no error
(`--plugin-dir`, no network, 2026-10-04), and 2.1.286 and 2.1.289 still log
`hooks module orchestrate@inline loaded`. `ModuleDeclarationTests` in
`tests/test_claude_plugin_packaging.py` now refuses a hooks file that names a
module without a `hooks` object. One corner is
unverified: a build between 2.1.242 and 2.1.284 with the rollout flag turned on
server-side, loading a module whose API it does not know. The flag could not be
forced locally.

**The adapter's TypeScript is not type-checked in CI, and that is accepted for
now.** `claude plugin validate` does not type-check, and the tsconfig the
engine generates covers only `hooks`, `types` and `tests` at a plugin root, so
nothing compiles `com.infiquetra.claude/mods/` against
`com.infiquetra.claude/types/index.d.ts`. A `tsc` step would need this build's
`claude-code` declarations, which the engine writes only into a folder it loads
in a session, not during `claude plugin validate` or `claude plugin test`; CI
has no step that produces them today. Two cheaper guards stand in:
`KNOWN_SCHEMA` is typed as the contract's `SagaRunRecordSchema`, and
`plugins/saga/tests/test_mod_run_record_contract.py` checks that the failure
reasons `run-record.ts` returns are exactly the contract's `SagaRunReadFailure`
members (renaming `'error'` in the contract fails it). The adapter did
type-check clean on 2026-10-04 with TypeScript 5.9.3 against the 2.1.289
declarations bundled with the plugin-authoring skill, using the engine's own
compiler options plus `allowImportingTsExtensions`; renaming `'error'` in the
contract then failed with `TS2322`. Revisit when a mod's logic outgrows these
guards, or when the engine can write its declarations without a session.

**Rejected alternatives.** A separate hooks file for the module, which the card
named as the fallback if an older build rejected the shared file; no build did.
Installing the CLI in the `validate` job, which must stay standard-library only.
A floor of 2.1.242 or 2.1.285, neither of which loads the module without a flag
or an environment variable. A floor of 2.1.289, which would refuse three builds
that load and test the module without trouble today.

**Revisit when.** A mod needs an API newer than the floor (raise
`CLAUDE_CODE_FLOOR`, the CI matrix and this entry together); the npm `stable`
tag reaches 2.1.286 or later; or the mods API leaves early access.

**Refs.** Issue #101; `plugins/saga/com.infiquetra.claude/`,
`plugins/orchestrate/com.infiquetra.claude/hooks/hooks.json`,
`.github/workflows/ci.yml` (`claude-mods`), `scripts/check_repo.py`
(`check_claude_module_sources`), `tests/test_claude_plugin_packaging.py`
(`ModuleDeclarationTests`, `TypesContractTests`, `ClaudeCodeFloorTests`).
### Saga's builder runs on Claude opus/medium through a Claude-only implementation work shape, resolved one way

**Decision.** The `worker` role, which implements plan units, moves off the `mechanical` work shape
(`sonnet/medium`) onto a new `implementation` work shape at `opus/medium` in
`plugins/fleet-core/scripts/fleet_commons/staffing.json` (issue #93). The shape is declared
`claude_only`, so a role pinned to another vendor through it fails loud instead of having `opus`
translated into that vendor's execution class. Admission, `/plan`, `/work` and
`intent_envelope.recommend_tier` all get a tier from `staffing.resolve_shape`, whose precedence is
written once in `staffing.TIER_PRECEDENCE`: the operator's answer, then the repository overlay
(`.saga/tier-defaults.json`), then a Jev-applied raise recorded in the run record, then the work
shape's default. A recorded raise must be exactly one model rung or one effort rung above the
default and never names `fable`; `max` is off the Claude palette. An unattended run does not step
the `implementation` shape one rung cheaper. The ordinal cost table (`cost_weights.py` and
`cost_weights.json`) is deleted.

**Rationale.** The worker was filed in the wrong category: `mechanical` is defined as
deterministic, scripted transforms, and implementing a plan unit that writes refund or IAM code is
not that. On the price side, Anthropic's pricing as read on 2026-10-03 and this machine's 30-day
transcript token mix (cache reads about 97 percent of input for both models) put Opus 5.5 at 1.36
to 1.37 times Sonnet 5.5, not twice; the deleted ordinal table claimed 2.67 times and nothing but
its own test read it. Three paths disagreed before this change: admission resolved role then shape,
`/plan` named two functions that no longer existed, and `/work` called the policy layer directly,
which also skipped the repository overlay admission honoured. One function with one written order
is the only way to keep them agreeing.

**Rejected alternatives.**

- Re-tier `mechanical` globally to `opus/medium`. It would also move the merging and release
  workers, the `contract-test` alias and every genuinely mechanical subagent, none of which the
  evidence covers.
- A per-repository overlay only. Every repository would have to opt in, the fleet default would
  stay wrong, and `.saga/` is gitignored in this repository, so the overlay is not even shared here.
- Keep the unattended one-rung step-down for `implementation`. Unattended runs would put the
  builder back on Sonnet, so the cost-per-unit measurement (staffing U3) would never test the Opus
  decision on those runs.

**Revisit when.** Measured cost per completed unit (staffing U3, issue #95) shows Opus at medium
losing to Sonnet at medium for the builder.

## 2026-09-22

### A notice is corrected, never superseded, when its assessment finally lands

**Decision.** The 2026-09-22 ten-client run produced a current matrix for three
packages whose evidence chain ended at a notice. Each notice is corrected in
place to name the new matrix and keeps `matrix-status: notice`. None is marked
superseded, and no historical record is repointed at a new matrix.

**Rationale.** The two rules that landed with the notice status decide this
between them. `check_document_status` refuses a notice that carries
supersession directives, because a notice is not a supersession and names no
successor of its own. `check_notice_discipline` refuses an assessment-free
document that resolves to `current`. So a notice has exactly one status
available to it, and correcting its prose is the only way to keep it true once
the assessment it anticipated exists. Nothing else has to move: a superseded
document may name a notice as its successor, so every existing chain stays
valid unedited.

**Rejected alternatives.** Mark each notice superseded by its new matrix and
repoint its dependents. The checker refuses the first half outright, and the
second half would have rewritten the supersession reasons on fifteen records
that are correct as published and edited five pinned assertions in
`tests/test_check_compatibility_matrix.py` — the assertions that exist to make
a moving chain visible to a reviewer rather than absorbed in a diff.

**Revisit when.** A package that has a notice gets a second assessment. The
correction is the same each time: update the notice's prose and its notice
record to name the current matrix, and leave the chain alone.

### The custody-move run: decisions taken while it ran

**Decision.** Six calls were made during the 2026-09-22 import run and are
recorded here rather than in each package narrative, because each binds more
than one package.

1. *`home-lab-ops` keeps the lab topology it inherited.* Its skills and
   team-scaffold specs name hosts by address exactly as the public upstream
   did, so the import creates no new exposure; site-neutralizing them into an
   operator site profile (as UniFi did) is queued, not done.
2. *A documentation mutation proof is re-run at the release that changes the
   docs, never re-bound.* The agent-launcher import first recomputed the
   digests of its portable-docs proof; that was refused and the eleven classes
   were re-run and published as a 2026-09-22 document superseding the
   2026-08-27 one. Same rule as tooling proofs (cycle 17).
3. *Compatibility records are never hand-rebound.* The fleet-core import first
   rebound the UniFi and Mission Control fingerprints; the records were
   restored to their assessed bytes once the version-bound check made a moved
   tree a report rather than a failure.
4. *Two packages whose tests resolve each other from the tree merge as one
   pull request.* Mission Control's tests resolve the saga plugin by repo
   walk-up and saga's validator test resolves Mission Control's root Claude
   manifest; each import failed CI alone and passed locally only because
   installed Claude plugins satisfied the ladder. PR #78 carried both.
5. *Repository-level tests that only describe a derived package skip with a
   stated reason rather than being deleted in the import.* Twenty-six such
   skips exist after the run; deleting them or moving them onto a synthetic
   derived fixture is queued.
6. *Captured fixture transcripts keep the machine paths they recorded.* Two
   packages (agy, saga) carry captured transcripts naming this machine's
   paths; they are inert data, not defaults, and scrubbing them is queued.

**Rejected alternatives.** Re-running a ten-client assessment inside each
import (the fingerprint-bound regime; refused by the version-bound rule).
Hand-editing evidence digests to keep CI green (refused twice, see 2 and 3).
Merging Mission Control with an admin override to break the circular
resolution (would have left main red between the two merges).

**Revisit when.** The queued items in 1, 5, and 6 land; or a future import
finds a third package in a resolution cycle, at which point the resolver's
repo walk-up should accept a fixture root in tests instead of the live tree.

**Closure (2026-09-22, end of run).** The review's findings closed as follows:
finding 1 by PR #81 (the agent-launcher readback restored to the bytes it
assessed and superseded), finding 2 by PR #86 (a `notice` document status, a
per-package current-matrix report, a machine-path scanner, mutation-proof
cycles 19 and 20), finding 3 by PR #82 (three saga tests carried), findings 4
to 10 by PR #84. Installer defects found during the cutover closed by PR #83
(idempotent placement, `--client all` continuing past a failure,
`not-applicable` readback) and PR #85 (Grok legacy removal by marketplace
name). The ten-client assessment landed as PR #87: twelve packages carry a
`docs/evidence/2026-09-22-<package>-compatibility-matrix.md` bound to their
shipped version; house-style and fleet-core are blocked on harness defects
recorded in QUEUED.md. The cutover then ran
`install_client.py --client all --uninstall-legacy --execute`, which removed
nine Claude plugin registrations and the `infiquetra-plugins` marketplace,
Cursor's old marketplace, and Grok's legacy marketplace; Grok's four orphaned
plugin entries were removed by observation (LEARNINGS.md, same date). The
final readback records infiquetra-claude-plugins nowhere. The only non-catalog
placements left are six Antigravity packages from
infiquetra-antigravity-plugins and OpenCode's saga skills from
infiquetra-opencode-plugins, both dedicated repositories outside this
retirement. Item 6 above is done (PR #84). Archiving infiquetra-claude-plugins
waits for the operator.

### Codex packaging sits at the repository root because the Codex CLI looks nowhere else

**Author.** Grok (custody-move unit U5b, branch `mg/codex-pkg`)

**Decision.** This catalog is installable by OpenAI Codex CLI 0.155.1.
`scripts/sync_codex_packaging.py` writes two kinds of file, and
`scripts/check_repo.py` refuses a stale copy:

- `.agents/plugins/marketplace.json` at the repository root. Its `name` is
  `infiquetra-agent-plugins`. Each entry's `source` is
  `{source: local, path: ./plugins/<package>}`, and its `policy` is
  `installation = AVAILABLE`, `authentication = ON_INSTALL`.
- `plugins/<package>/.codex-plugin/plugin.json` for every package that has a
  portable `plugin.json`. `name`, `version`, and `description` come from that
  portable manifest. `skills` is `./skills/` when that directory exists.
  `mcpServers` is a path to `com.infiquetra.codex/.mcp.json` only when that
  adapter file exists. The manifest has no `hooks` and no
  `interface.defaultPrompt`.

`scripts/install_client.py` places the catalog with `codex plugin marketplace
add <checkout>` and then `codex plugin add <name>@infiquetra-agent-plugins`.
`--check` reads `[marketplaces.*]` and `[plugins."<name>@<marketplace>"]` in
`~/.codex/config.toml`. An existing registration of the marketplace name is
not retargeted. `infiquetra-codex-plugins` is not modified, and this unit
does not write the operator's Codex config.

**Rationale.** `codex plugin marketplace add --help` takes a local path.
The marketplaces already configured on this machine, the OpenAI bundled
marketplace, and `infiquetra-codex-plugins` all use
`.agents/plugins/marketplace.json` plus `.codex-plugin/plugin.json`. A
temporary `CODEX_HOME` accepted a checkout that also contains
`.claude-plugin/`, listed a plugin with no `interface.defaultPrompt` and no
`category`, and wrote the two config tables above. Marketplace add alone left
`installed` empty; plugin add set `enabled = true`. The installed
`google-cloud-developer` plugin contains both `.claude-plugin/` and
`.codex-plugin/`, which is the same sibling layout. The hash of
`~/.codex/config.toml` was unchanged across that probe.

**Rejected alternatives.** *Leave Codex `unsupported` because
`infiquetra-codex-plugins` rejects a plugin directory that also contains
`.claude-plugin`.* That rule is the dedicated repository's validator. The
CLI accepted the sibling. *Point `com.infiquetra.codex/marketplace.json` at
the packages.* The CLI does not load a marketplace from that path. *Put
`interface.defaultPrompt` or `hooks` in the generated manifest.* A prompt is
behaviour, and the CLI's bundled scaffold says validation rejects `hooks`.
The probe listed a plugin that had neither. *Reuse the marketplace name
`infiquetra-codex-plugins`.* That name is already the dedicated git
marketplace in the operator's config. A second checkout has to register
under the catalog's own name. *Retarget a marketplace name that already
points somewhere else, or run `plugin add` anyway.* `plugin add` takes
`name@marketplace` and no path, so it would install the other source.

**Revisit when.** A Codex release stops reading
`.agents/plugins/marketplace.json` at the repository root, or starts
requiring `interface.defaultPrompt` or `hooks` for a plugin to be listed.
Also when a package in this catalog grows a real `com.infiquetra.codex/`
adapter whose behaviour the manifest should point at by path.

### The catalog installer places each harness the way that harness already loads a package, and records Codex as unsupported

**Decision.** `scripts/install_client.py` is the cutover placement for this
catalog. It prints its plan unless `--execute` is passed. Per harness:

- Claude installs `name@infiquetra-agent-plugins` from the root marketplace
  file. An existing registration of that name is not duplicated and is not
  retargeted at the checkout that happens to be running the script.
- Cursor's client binary is `cursor-agent`. The marketplace add takes
  `https://github.com/infiquetra/infiquetra-agent-plugins`. A second add is
  skipped when that repository's cache already contains a marketplace file.
- Qwen, Grok, and Agy install the package directory (`qwen` with the `y`
  confirmation the assessment supplies, Grok with `--trust`). Qwen's install
  record and an Agy sidecar manifest are set to that directory so a later
  readback can tell this checkout from any other source. An Agy directory
  that already exists without that sidecar is not replaced.
- OpenCode and Hermes get a symlink per skill unit plus a manifest in the
  shape already used at `~/.config/opencode/.infiquetra-plugins.json`.
  OpenCode's destination is `~/.config/opencode/skills/`, which is where that
  manifest already points. Hermes's `skills install` accepts a registry
  identifier or an HTTP URL, and the live profile already loads a symlink, so
  the installer symlinks instead of copying.
- Gemini runs `skills link` with the same `y` on stdin the assessment used.
  Muse runs `skills install --scope user`. Both write the same kind of
  manifest. An existing destination that we did not record is left alone.
- Codex was recorded `unsupported` in this entry. Placement is now the
  decision "Codex packaging sits at the repository root because the Codex CLI
  looks nowhere else", earlier in this dated section.
  `infiquetra-codex-plugins` is still not modified.

`--uninstall-legacy` removes a placement only when its recorded source is
`infiquetra/infiquetra-claude-plugins`. A copy with no source record is
refused. `infiquetra-codex-plugins`, `infiquetra-opencode-plugins`, and
`infiquetra-antigravity-plugins` are never removed. `--check` prints
`installed-from-catalog`, `installed-from-elsewhere (<source>)`, or `absent`,
and exits 1 only when a package is absent. Codex's unsupported line is not an
absence.

**Rationale.** The compatibility matrices and `scripts/assess_clients.py`
already say how each client places a package. Re-deriving that, or writing a
Codex manifest the package directories cannot satisfy, would make cutover
look done when the client's own files would disagree.

**Rejected alternatives.** *Generate `.agents/plugins/marketplace.json` and
`.codex-plugin/plugin.json` from the portable manifest* — those Codex plugins
are required not to contain `.claude-plugin`, which every Claude-installable
package here does. *Retarget the existing Claude directory registration at
the worktree running the script* — the registration is already this
repository's primary checkout; a worktree must not steal it. *Copy skills
into `~/.agents/skills` for OpenCode* — that is the isolated-home assessment
path. The machine's Infiquetra OpenCode install is the symlink manifest under
`~/.config/opencode/`. *Treat the marketplace name `infiquetra-plugins` as
the old repository* — on Agy that name is the Antigravity repository.

**Revisit when.** A package in this catalog ships a real `.codex-plugin/`
adapter, or a harness changes the placement the matrices recorded.

### Custody moves here: every package becomes authored, and infiquetra-claude-plugins retires

**Decision.** The repository-level custody question that the 2026-08-21 pilot
decision left "deliberately unanswered" (see the archived entry "Choose the
first portability pilot and custody gate") is answered: source custody for
every Infiquetra plugin moves to this repository. `infiquetra-claude-plugins`
(13 live plugins at commit `acc99fe7`) is imported once, package by package,
and then archived read-only on GitHub after every harness on the operator's
Mac Studio has been read back as installing from here. The run plan is
[`docs/plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md`](../plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md).

Four rules change with it:

1. A package with no `PROVENANCE.json` is authored here; after import every
   package drops its manifest, and the import SHA lives in `CHANGELOG.md`.
2. Port descriptors gain an authored mode (schema version 4, `source` and
   `custody` optional; the `assessment` safety block stays mandatory).
3. Every package is Claude-installable from this repository: a root
   `.claude-plugin/plugin.json` per package and a marketplace that lists all
   of them. This is the operator decision `QUEUED.md` P1 was waiting on, so
   the agent-launcher test asserting "voice only" retires with it.
4. Compatibility evidence binds to a released package version, not to every
   tree; a version bump without a fresh ten-client run fails the check, a tree
   that moved under an unchanged version is reported, not failed.

**Rationale.** The derived-artifact model existed to keep one writable source
while the portable layout was unproven. Three ports (UniFi, Mission Control,
agent-launcher) and one authored package (voice) proved it across ten clients
with zero failures. Keeping two writable sources after that is the thing the
architecture brief warned against ("exactly one writable source for shared
behavior"), and the old repository is the one Claude Code no longer needs now
that it reads `AGENTS.md`. Fingerprint-bound evidence was right for a package
whose bytes only change at a repin; for thirteen authored packages it would
demand a ten-client run per commit, which is a rule that would be broken
rather than kept.

**Rejected alternatives.** *Repin the three ported packages and keep
deriving* — leaves ten packages with no portable home and keeps the old
repository alive indefinitely. *Retire the old repository first and import
later* — violates the brief's "retire existing marketplaces before their
replacements are proven" non-goal; the archive is the last step here, not the
first. *Big-bang single import commit* — unreviewable; the plan imports one
package per branch with the same fixed recipe.

**Revisit when.** A second organization or machine needs to consume this
catalog through a distribution path that a git checkout cannot serve (Cursor
Agent's marketplace takes only a git URL). The Codex half of this condition
was met later on this date by "Codex packaging sits at the repository root
because the Codex CLI looks nowhere else". Revisit also when a harness on
the machine is found to have consumed the old repository through a path the
cutover missed.
### The Claude marketplace is generated, not hand-edited

**Author.** Claude for Jeff Cox (custody-move unit U1, branch `mg/tooling`)

**Decision.** `.claude-plugin/marketplace.json` is produced by
`scripts/sync_marketplace.py` from the packages that carry
`.claude-plugin/plugin.json`. Entries are sorted by package name; every field an
entry states about a package is read from that package's own manifests; the
catalog-level `name`, `owner`, and `metadata` block is preserved from the
existing file, as is each entry's `category`. `--check` compares the committed
file to the generated one, `check_repo.py` calls the same function, and
`tests/test_claude_plugin_packaging.py` asserts committed equals generated
rather than restating the listing rule.

**Rationale.** Twelve import units each add one entry to one array. Hand-edited,
that is twelve merge conflicts on one file, each resolved against a diff in
which nobody can see whether the result is correct. Generated, a conflict is
resolved by re-running the script. Deriving each field from the package's own
manifests also makes the agreement `claude plugin tag` requires -- entry and
manifest stating the same name and version -- true by construction rather than
by a test that catches it afterwards.

**Rejected alternatives.** Keep it hand-edited and rely on the packaging test to
catch mistakes (the test catches a wrong file; it does not resolve twelve
conflicts). Derive `category` from a manifest (neither manifest has a home for
it, and inventing a field in the Agent Plugins schema, which this repository
does not own, is a worse cost than preserving one string). Derive the whole file
including the catalog block (nothing under `plugins/` describes the catalog, so
it would have to be invented in the script instead).

**Revisit when.** The Claude marketplace format gains a field that is neither
derivable from a package manifest nor stable across regeneration.

**Refs.** `scripts/sync_marketplace.py`, `scripts/check_repo.py`
(`check_marketplace_manifest`), `tests/test_sync_marketplace.py`,
`tests/test_claude_plugin_packaging.py`
(`test_the_committed_file_is_the_generated_one`).

### CI's plugin-test dependencies move into a requirements file

**Author.** Claude for Jeff Cox (custody-move unit U1, branch `mg/tooling`)

**Decision.** `requirements-plugin-tests.txt` at the repository root lists what
the `plugin-tests` job installs, and the job installs that file. The `validate`
job stays dependency-free.

**Rationale.** Same shape as the marketplace: twelve import units may each need
a test-time package, and twelve branches editing one `pip install` line is
twelve conflicts on one line. Appending a line to a sorted file is a conflict
git can usually resolve, and one a human can always read. The `validate` job is
deliberately left alone: it is the repository's hermetic baseline, and giving it
a requirements file would invite exactly the dependency the baseline exists to
refuse.

**Rejected alternatives.** One requirements file for both jobs (would let a
dependency reach the hermetic job). Per-package requirements files (nothing
installs them; the job would have to glob, which is a second rule).

**Revisit when.** The plugin suites need per-package dependency isolation, at
which point a single flat list stops being the right shape.

**Refs.** `requirements-plugin-tests.txt`, `.github/workflows/ci.yml`,
`tests/test_sync_vendor_source.py`
(`test_the_ci_dependency_list_keeps_pyyaml`).

### Authored mode states nothing rather than stating emptiness, and the sync refuses it

**Author.** Claude for Jeff Cox (custody-move unit U1, branch `mg/tooling`)

**Decision.** In port descriptor schema version 4, an authored package's
`source` and `custody` are `None` on the parsed `PortConfig`, not empty objects,
and `sync_vendor_source.require_derived` refuses such a descriptor at the
module's single entry point (`load_config`) and again inside
`classify_source_tree`. `PortConfig.is_authored` is the question a caller asks.
The two fields are optional as a pair and never singly.

**Rationale.** Every other object in a descriptor is closed because an unknown
key is a setting that silently did not take effect. The same asymmetry applies
here in the other direction: an empty custody table does not read as "this
package has no upstream", it reads as "nothing is classified", and
`classify_source_tree` would then have no path to preserve and
`plan_sync` nothing to copy. An authored package's tree is the only copy of
itself, so a synchronization that took that reading would report success having
deleted the managed paths of the only copy. `None` makes the same mistake an
`AttributeError`, and the explicit refusal makes it a sentence. Refusing one
half without the other follows the same logic: a `source` with no `custody` is a
synchronization with no classification table, and a `custody` with no `source`
classifies paths in a repository nobody named.

**Rejected alternatives.** Empty `SourceConfig` and `CustodyTable` objects
(reads as "nothing to do", which is the fail-open shape this repository already
rejects for safety fields). A separate `mode` field naming "derived" or
"authored" (a third thing to keep in agreement with the two fields that already
say it, and a descriptor whose `mode` disagreed with its contents would have to
be adjudicated). Leaving the refusal to argparse's `--source` requirement alone
(it guards the command line, not a programmatic caller, and the run plan has
twelve units calling this tooling).

**Revisit when.** A package needs to be re-derived from an upstream after
custody has moved -- which would mean the custody decision is being reversed,
not that this shape is wrong.

**Refs.** `scripts/port_config.py` (`SCHEMA_VERSION`, `DERIVATION_FIELDS`,
`is_authored`), `scripts/sync_vendor_source.py` (`require_derived`),
[`ports/README.md`](../../ports/README.md) ("Derived and authored packages"),
`tests/test_port_config.py` (`AuthoredModeTest`).

### An import carries a shim use it cannot rewrite, names it, and exits non-zero

**Author.** Claude for Jeff Cox (custody-move unit U1, branch `mg/tooling`)

**Decision.** When `scripts/import_vendor_package.py` finds a
`fleet_commons_shim` use that none of the three `resolve-bundled-fleet-module`
rules matches, it writes the file unchanged, lists it under `UNRESOLVED` in the
summary, and returns exit status 1 with the tree written. `--dry-run` reports
the same list and exits 1 before writing anything. Any module such a file
reaches is still declared in the generated `fleet-bundle.json`.

**Rationale.** Measured against the real upstream at `acc99fe7`: four of the
thirteen packages (`saga`, `mission-control`, `orchestrate`, `agy`) use the shim
in a shape outside the rule family -- inside a function, or loading two modules
from one file. `saga` alone has nine such files. A hard stop would mean those
four packages could not be laid out at all, and the plan's per-package recipe
already has a step for exactly this work ("fix what the transform could not").
Carrying the file silently is the other failure: an unrewritten shim import is a
package that imports a module nothing generated, which installs cleanly and
fails at first invocation, and is the defect AGENTS.md records against the UniFi
clients. Non-zero with the tree written is the only outcome that both lets the
work continue and refuses to call it finished.

**Rejected alternatives.** Stop the import on the first unmatched file (blocks
four packages on work the recipe assigns to a later step). Carry it silently and
let a later check catch it (nothing checks for a shim import today, so "later"
is the first invocation on the operator's machine). Extend the rule family to
cover the new shapes (each rule is a versioned rewrite with its own proof
obligations; inventing three more inside an import tool would put the rewriting
authority in two places, which is what the descriptor schema already refuses).

**Revisit when.** The rule family grows to cover the function-scope and
multiple-load shapes, at which point the unresolved list should be empty for
every upstream package and a hard stop becomes affordable.

**Refs.** `scripts/import_vendor_package.py` (`apply_fleet_rule`,
`unresolved_shim_files`), `tests/test_import_vendor_package.py`
(`UnresolvedShimTests`), `AGENTS.md` (the runnable-not-merely-present rule).

### The shim's own source file is dropped by default, not per package

**Author.** Claude for Jeff Cox (custody-move unit U1, branch `mg/tooling`)

**Decision.** `import_vendor_package.py` drops any file named
`fleet_commons_shim.py`, wherever it sits in the upstream package, and reports
it as not carried with the reason.

**Rationale.** `ports/mission-control.json` already records this drop, with the
reason that the build-time Fleet Core bundle replaces the shim and its
resolution ladder is Claude-specific runtime discovery the portable package must
not retain. That is not a judgement each of twelve packages should re-argue; it
follows from the catalog's own rule that Fleet Core is bundled at build time and
never discovered. UniFi carries the file twice and mission-control once, and the
committed ports drop all three.

**Rejected alternatives.** Classify it as an entrypoint transform (there is
nothing to rewrite; the file *is* the ladder). Leave it to each import unit's
descriptor (twelve chances to carry the one file whose whole purpose the port
removes).

**Revisit when.** Fleet Core stops being bundled at build time.

**Refs.** `scripts/import_vendor_package.py` (`DROPPED_FILE_NAMES`),
`ports/mission-control.json` (`provenance.dropped_reason`),
`tests/test_import_vendor_package.py`
(`test_the_shim_source_file_is_dropped_rather_than_carried`).

### A non-failing report is an out-parameter, not a changed return type

**Author.** Claude for Jeff Cox (custody-move unit U1, branch `mg/tooling`)

**Decision.** `check_compatibility_matrix.check_matrix` keeps returning
`list[str]` of problems and gains an optional `reports: list[str] | None`
parameter that collects non-failing observations. `check_document_status` takes
the same parameter. `main` prints the collected reports whether the run passed
or failed.

**Rationale.** A report is by definition not a problem, so a caller asking "is
this matrix valid" should not have to unpack a tuple to find out. Returning
`(problems, reports)` would have changed the signature every one of the 164
existing tests in `tests/test_check_compatibility_matrix.py` calls, turning a
behaviour change into a mechanical rewrite of the file that proves it -- which
is how a rule change stops being reviewable. Printing reports on failing runs as
well as passing ones is deliberate: a report that appeared only on a green run
would be invisible exactly while a package is being repaired.

**Rejected alternatives.** A `(problems, reports)` tuple return (rewrites the
suite that guards the change). A module-level accumulator (makes two runs in one
process share state, which the tests do). Logging (the tool is standard-library
only and its output is read by a human at a terminal, not collected).

**Revisit when.** A second kind of non-failing observation appears and the two
need to be distinguished by category rather than by message.

**Refs.** `scripts/check_compatibility_matrix.py` (`check_matrix`,
`split_binding_problems`), `tests/test_check_compatibility_matrix.py`
(`VersionBoundEvidenceTest`, `check_with_reports`).

### The Claude-installable set is derived from the tree, and the marketplace must equal it

**Author.** Claude for Jeff Cox (custody-move unit U1, branch `mg/tooling`)

**Decision.** `tests/test_claude_plugin_packaging.py` takes its subject to be
every `plugins/*/` carrying `.claude-plugin/plugin.json`, with a subTest per
package, and requires `.claude-plugin/marketplace.json` to list exactly that
set in both directions. The per-package version agreement is derived from the
sites each package has, with no literal version written in the test.
`SubjectTests` fails when the derived subject is empty.

**Rationale.** The module named `plugins/voice` in a constant, so the rules it
carries applied to one package while eleven more are about to arrive carrying
the same manifests. Deriving the subject is what makes each import unit's
package covered on the day it lands rather than on the day someone remembers to
add it here. Both marketplace directions are checked because the two failures
are different bugs: an unlisted package is one nobody can install from this
repository, and a listed package with no root manifest is an entry whose install
ends in "No manifest found in directory". The version literal was itself a
version site that could drift from the five it was checking.

**Rejected alternatives.** Keep the voice constant and add a second module per
package (twelve copies of one rule). Derive the subject from the marketplace
instead of from the tree (a package missing from both would then be invisible,
which is the failure most worth catching). Keep the literal version as a
release-gate cross-check (a sixth hand-edited copy of the number the other five
already have to agree on).

**Revisit when.** A package needs to ship a root Claude manifest without being
distributed through this marketplace, which would make the equality wrong rather
than the derivation.

**Refs.** `tests/test_claude_plugin_packaging.py`,
`tests/test_agent_launcher_packaging.py` (the retired assertion),
[`QUEUED.md`](QUEUED.md) (the P1 entry this consumes).

---

### house-style ships as a Claude-only package

**Decision.** `plugins/house-style` carries no portable core: no scripts, no
skills, no executable entrypoint. What it ships is one Claude Code output
style (a harness feature that governs the shape of a Claude Code turn — which
turns are full orientations and which are deltas, the closing block, when a
visual is required) plus two reference documents other packages copy as text.
The package's `plugin.json` and README both disclose, in plain terms, that
this is a Claude-only package.

**Rationale.** An output style has no vendor-neutral form; it is a Claude Code
concept with no equivalent contract in another harness this catalog targets.
The package is carried anyway, because Claude Code is one of the harnesses
this catalog installs into and dropping the style would mean losing a style
operators already use there. house-style is, as a result, the one package in
this catalog that a skill-scoped harness — one that can install a skill or a
script but has no notion of an output style — cannot use at all.

**Rejected alternatives.** Drop the package rather than carry a Claude-only
capability: rejected, because it deletes a style operators use today with no
replacement. Invent a portable "style" format other harnesses could read:
rejected, because nothing on the other side consumes such a format, so a
portable shape would be speculative engineering with no second implementation
to validate it against.

**Revisit when.** A second harness this catalog targets gains an equivalent
output-style capability, at which point a portable core for the style becomes
worth designing against two real consumers instead of one.

**Refs.** [`plugins/house-style/README.md`](../../plugins/house-style/README.md),
[`plugins/house-style/plugin.json`](../../plugins/house-style/plugin.json).

## 2026-08-30

### Mission Control 2.15.2 resync run plan: bind the identity surface, route around the graded files, freeze after the last package edit

**Author.** Jeff Cox and Claude (Saga Plan for issue #50)

**Decision.** The Mission Control resynchronization run plan
([docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md](../plans/2026-08-30-issue-50-mission-control-resync-plan.md))
fixes thirteen plan-level choices inside the operator-settled contract of issue
#50. Six are load-bearing enough to record here. (1) **The identity surface is
bound, never retyped**: `plugins/mission-control/plugin.json`'s version is
derived by test from `PROVENANCE.json`'s `source_version`, and the root
`README.md`'s file count, test counts, and Packages-table row are pinned by a
test that recomputes them from disk (KTD5, KTD6). (2) **The third dropped path
extends the existing single `provenance.dropped_reason` string** rather than
promoting it to a per-path mapping, because the mapping is a descriptor schema
change and `scripts/port_config.py` is graded (KTD3). (3) **The new evidence
bindings are added as parallel mission-control classes in
`tests/test_check_compatibility_matrix.py`**, never by teaching the graded
`scripts/check_compatibility_matrix.py` and never by parameterizing UniFi's live
classes (KTD4). (4) **The fingerprint freeze follows U3, not U2**, because U3 is
the last unit that edits bytes inside the package root, and U4 is made
fingerprint-neutral by construction so the two may run concurrently (KTD9,
KTD10). (5) **The replacement post-activation readback keeps a
`cycle_16_verification` block** with the five graded-file digests recomputed at
the new freeze, turning it into a positive statement that the resync retired no
mutation proof (KTD11). (6) **The run lands as one squash-merged pull request**;
`mergeCommitAllowed` is false and every commit on `main` since #35 is a squash,
so each child records its base and frozen SHAs from the branch alongside the
shared merged SHA (KTD8).

**Rationale.** The #9 run's only review finding was a hand-transcribed identity
row with no derivation and no pin test; retyping five version and count claims
one release later reproduces that defect exactly, so the plan closes the class
rather than the instance. The five cycle-16 graded files still match the proof's
footer digests on the current tree, and a resynchronization needs none of them,
so every place a unit might reach for one has a named non-graded alternative
decided in advance rather than discovered under pressure. The package
fingerprint is computed from every byte under the package root, which makes the
freeze point arithmetic rather than preference. And `check_document_status`
refuses a superseded stamp while the document's fingerprint still identifies the
package, so the supersession order — land the resync, run the assessment,
publish the successor as current, only then stamp the predecessor — is enforced
by code, not by discipline.

**Rejected alternatives.** *Retyping the version and count claims* with reviewer
discipline as the control — that is precisely what failed in #9's U9. *A
per-path `dropped_reason` mapping* and *teaching the compatibility checker about
mission-control* — both cleaner, both retire the cycle-16 mutation proof for a
cosmetic gain. *Parameterizing the existing UniFi binding classes* — risks live
passing bindings on a package this run does not touch. *Freezing after U2 and
treating U3's edits as documentation-only* — the fingerprint does not care what a
file means. *Rebase-merging to keep six commits on `main`* — allowed by settings,
but rebase rewrites the SHAs anyway, so the traceability gain over recording
branch SHAs is marginal and it would be this repository's first non-squash
landing. *Carrying `tests/test_card_validator_agreement.py` and letting it skip
at runtime* — the same call the `test_prompt_alignment.py` drop already rejected.

**Revisit when** a fourth package needs evidence bindings (the moment
parameterization earns its risk), or when a funded unit re-runs the mutation
proof and the graded-file constraints that shape KTD3 and KTD4 no longer apply.


### Spoken approval forwarding in PreToolUse supersedes KTD7 and lifts plan stop-condition 4 for Unit U6

**Author.** Claude for Jeff Cox (Auralis C3 adapter U6 approval hook completion, issue #46, branch `orch/auralis-c3-adapter-build-c3-u6-approval-hook`)

**Decision.** The Claude Code adapter's `PreToolUse` hook (`com.infiquetra.claude/hooks/pre_tool_use_hook.py`) is updated for Unit U6 (C8 Prerequisite 1) to actively forward tool execution approval requests to Auralis Core via `POST /v1/approval`. This supersedes the previous observe-only posture declared in KTD7 and lifts plan stop-condition 4 ("Any permission decision from the PreToolUse hook") exclusively for the spoken-approval route.
Specifically:
1. When covered by an active bridge binding, the hook forwards the full 9-key structured request (`schema`, `identity`, `binding_id`, `session_id`, `tool_use_id`, `tool_name`, `tool_input`, `permission_mode`, `cwd`) to `POST /v1/approval` and awaits Core's decision.
2. The hook emits `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}` strictly and exclusively when Core returns `decision: "allow"` with an exact match on `tool_use_id` AND a canonically complete snapshot match across `tool_use_id`, `tool_name`, `tool_input`, `cwd`, and `classification` (`result: "voice_approvable"`, `permission_mode: original_mode`).
3. On every other outcome — Core `defer` decision, snapshot mismatch, identifier mismatch, missing payload field, transport error, socket close, 401/500 status, or timeout — the hook defers fail-closed (exits 0 with no stdout output, leaving the tool decision entirely to Claude Code's native UI prompt).
4. No secondary allow-list or independent tool classifier is added to the adapter; classification authority belongs exclusively to Auralis Core per R78 and KTD4.

**Rationale.** KTD7 originally adopted an observe-only posture because C3 did not yet have an approval surface on the bridge wire. With C8 Prerequisite 1 landing the normative `POST /v1/approval` endpoint in Auralis Core, spoken tool approval requires the adapter hook to forward requests and emit the `allow` decision when approved by voice. Restricting emission to verified canonical snapshot equality and failing closed on any deviation preserves safety invariants without double-classifying.

**Rejected alternatives.** Independent allow-list filtering in the adapter hook (violates Core's classification custody and proportionality rule); emitting `deny` decisions from the hook (the hook's contract is to allow approved voice actions or defer to standard UI interaction).

**Revisit when.** Auralis Bridge Contract v2 changes approval wire formats, or Claude Code changes PreToolUse hook output schema.

**Refs.** [`docs/plans/2026-08-27-auralis-c3-adapter.md`](../plans/2026-08-27-auralis-c3-adapter.md),
[`docs/bridge-v1-from-c10.md`](../bridge-v1-from-c10.md),
`plugins/voice/com.infiquetra.claude/hooks/pre_tool_use_hook.py`,
`plugins/voice/tests/test_pre_tool_use_hook.py`.

### Auralis bridge v1 contract snapshot refresh and voice 0.4.0 approval-hook release

**Author.** Claude for Jeff Cox (Auralis C3 adapter completion & U6 approval hook, branch
`orch/auralis-c3-adapter-build-c3-u6-approval-hook`)

**Decision.**
1. Refreshed [`docs/bridge-v1-from-c10.md`](../bridge-v1-from-c10.md) to a byte-identical
tracked snapshot of `docs/bridge/bridge-v1.md` on `infiquetra/auralis` `main` at commit
`0d1faf6ac146ee69cc5c63eea4229f6a0c09cf82` (SHA-256
`9b78f4a417700c27b3650858597bd5b968fa69302c0dff589301476b8d30c059`), incorporating the
6th route (`POST /v1/approval`), closed 9-key request validation, allow/defer response schemas,
60s/55s/50s nested timeout discipline (KTD15), and `applyConfirmedForBinding()`.
2. Bumped the voice plugin version from `0.3.0` to `0.4.0` across all five declaration sites
(`plugins/voice/.claude-plugin/plugin.json`, `plugins/voice/plugin.json`,
`plugins/voice/com.infiquetra.claude/plugin.json`, `.claude-plugin/marketplace.json`,
`plugins/voice/scripts/mcp_server.py`) and locked by `tests/test_claude_plugin_packaging.py`.
3. Documented `PreToolUse` tool approval forwarding and validation in `plugins/voice/README.md`
and captured acceptance evidence across all 24 U6 approval test cases in
[`docs/evidence/voice/auralis-c3-acceptance.md`](../evidence/voice/auralis-c3-acceptance.md).

**Rationale.** Unit U6 introduces spoken tool approval routing into the Claude Code adapter —
a functional capability addition beyond the initial 0.3.0 bridge baseline. Tracking the
normative Auralis contract hash and synchronizing all five version sites guarantees release
integrity and prevents package cache staleness in Claude Code plugins.

**Rejected alternatives.** Leaving the contract snapshot at 5 routes (diverges from
production Core); bumping version selectively (violates 5-site agreement invariant);
omitting fail-closed deferral on transport errors (risks unapproved execution).

**Revisit when.** Auralis bridge contract v2 introduces protocol schema changes or changes
approval route shape.

**Refs.** [`docs/bridge-v1-from-c10.md`](../bridge-v1-from-c10.md),
[`docs/evidence/voice/auralis-c3-acceptance.md`](../evidence/voice/auralis-c3-acceptance.md),
`plugins/voice/tests/test_pre_tool_use_hook.py`, `tests/test_claude_plugin_packaging.py`.

### Mission Control 2.15.2 resync U1: eight new upstream tests classified — seven hermetic byte copies, one exclusion — and the prompt-alignment drop re-verified at the new pin

**Author.** Claude for Jeff Cox (U1 of issue #50, child #52, branch `orch-agent-plugins-50`)

**Decision.** (1) The seven hermetic upstream tests that 2.15.2 adds
(`test_lifecycle_field_boards.py`, `test_lifecycle_field_identity.py`,
`test_lifecycle_field_mutation.py`, `test_lifecycle_field_routing.py`,
`test_lifecycle_writer_census.py`, `test_option_identity.py`,
`test_sdlc_manager_optional_deps.py`) are classified `upstream-byte-copy` in
`ports/mission-control.json` (`custody.byte_copies` grows 42 → 49). Each claim
was re-verified first-hand against the pinned upstream, not inherited from the
issue text: six patch `_graphql` at the `sdlc_manager` module level so no live
GitHub call can occur, and their docstrings state it; the seventh
(`test_lifecycle_writer_census.py`) is a static AST census over
`sdlc_manager.py` source using only the standard library; and
`test_sdlc_manager_optional_deps.py` spawns a subprocess of the test's own
interpreter (`sys.executable -c`) with `sys.modules['yaml']` forced to `None` —
package-internal and hermetic. A grep over all seven found no external
checkout, no marketplace or sibling-plugin premise, no network call, and no
credential. (2) `tests/test_card_validator_agreement.py` is excluded by
operator ruling 2 and recorded in `custody.dropped_from_source` (2 → 3
entries), with its reason appended to the single `provenance.dropped_reason`
string (KTD3 — the mapping alternative is a descriptor schema change that
touches the graded `scripts/port_config.py`). (3) `provenance.notes` were
refreshed in the same commit, because `scripts/sync_vendor_source.py` copies
them verbatim into `PROVENANCE.json`: the notes now name pin
`3b2b7083fdda8e39e213b5f4acf9f8301d60dd52` and version 2.15.2; the four
line-number claims were re-verified at the pin by `git show` and grep
(`_load_intent_envelope` guarded import block 5134–5140,
`INFIQUETRA_SDLC_PATH` read at 136, `_open_mapping_pr` at 5552,
`executor_profile_lint.py` still 35 and 89); the PyYAML claim was rewritten —
upstream filing #828 moved the import into the `_load_live_mimir_coverage`
function at line 3436, so the module-scope claim at line 83 is false at the
new pin, and the notes now state that PyYAML remains required because
`scripts/sync_template_docs.py:14` and `tests/test_template_sync.py:7` still
import it at module scope, so the continuous-integration install line stays
and only the justification changed; and the test count moved from
twenty-one to twenty-eight byte-copied test files (30 at the pin minus the two
dropped). (4) The `test_prompt_alignment.py` drop was re-verified at
`3b2b7083` and holds: the pinned file still reads the root
`.claude-plugin/marketplace.json` (line 41) and the sibling
`plugins/saga/skills/handoff/SKILL.md` (line 231), neither of which this
catalog hosts. The drop stands, and the re-verification is recorded here
rather than implied.

**Rationale.** The agreement test loads an authority module from outside any
repository — searching `HOME_LAB_PATH`, then `INFIQUETRA_HOME_LAB_PATH`, then
`~/workspace/infiquetra/home-lab`, then `~/workspace/home-lab`, then sibling
directories — and skips loudly when absent; its own docstring states this
repository's continuous integration never exercises it. Carrying it would make
a test's verdict depend on what else happens to be on the machine's disk,
which is the defect class `QUEUED.md` already names about the link checker: a
gate that reports the environment rather than the repository. The tool's
unclassified-paths refusal changed shape after this edit: it now reports real
content drift (byte-copy divergences and missing synchronized files for the
seven new tests), which is U2's input rather than a refusal.

**Rejected alternatives.** (a) Carry the agreement test and let it skip at
runtime — deadweight that misrepresents its own coverage; the recorded
`test_prompt_alignment.py` drop already rejected exactly this. (b) Carry it
with a repository-local stub of the home-lab authority module — makes the
portable copy assert agreement with a fake, which is worse than not asserting
it. (c) Classify it as a byte copy to make the tool stop complaining — the
tool refuses on *unclassified*, not on *wrongly classified*, so this would
silence the error and ship the defect.

**Revisit when** the home-lab authority module becomes available as a pinned,
in-repository dependency, or upstream moves either dropped test's premises so
they hold under the portable layout.

**Refs.** [`ports/mission-control.json`](../../ports/mission-control.json),
[`docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md`](../plans/2026-08-30-issue-50-mission-control-resync-plan.md),
issue #52, `tests/test_sdlc_manager_optional_deps.py` (upstream, at the pin).

### Mission Control 2.15.2 resync U2: `sync_template_docs.py` becomes a deterministic transform rather than an upstream filing

**Author.** Claude for Jeff Cox (Amendment 1 to the issue #50 run plan, taken by the
run coordinator during U2, branch `orch-agent-plugins-50`)

**Decision.** `plugins/mission-control/scripts/sync_template_docs.py` is reclassified
in [`ports/mission-control.json`](../../ports/mission-control.json) from
`upstream-byte-copy` to `deterministic-transform`, under a new versioned rule that
resolves the package root through the portable layout's own marker,
`com.infiquetra.claude/plugin.json`, instead of upstream's
`.claude-plugin/plugin.json`. The rule is authored by the U2 worker;
[the run plan](../plans/2026-08-30-issue-50-mission-control-resync-plan.md) records
the decision (KTD14, R40, R41, §14) and does not write the rule. U2 consequently
gains three files outside the package root, each with its writer order stated:
`scripts/sync_vendor_source.py` (sole writer), `ports/mission-control.json` (second
of three sequenced writers, after U1 and before U3), and
`tests/test_sync_vendor_source.py` (first of two, before U4).

**Rationale.** Upstream 2.15.2 rewrote this carried file so that
`_find_package_root()` (line 17 at pin `3b2b7083`) walks up for
`.claude-plugin/plugin.json` (line 20), raises `RuntimeError` when it finds none
(line 22), and is called at module scope (line 27). The portable package has no
`.claude-plugin/` directory — `relocate-claude-manifest` moves the Claude manifest to
`com.infiquetra.claude/plugin.json` — so the module cannot be imported here at all.
Reproduced on the U2 tree: four failures in `python3 -m unittest discover -s tests`
and two collection errors in the package suite trace to this single cause.

The run contract names two legitimate resolutions when a carried file cannot work
unchanged in the portable layout: an upstream filing, or a recorded custody decision.
An upstream filing blocks the whole resynchronization until upstream fixes and this
repository repins. The custody path has direct precedent here:
`normalize-skill-frontmatter` is the identical shape — upstream keeps a form the
portable layout cannot take verbatim, and a versioned rule transforms it
deterministically, reproducible from the source bytes alone — and the
`resolve-bundled-fleet-module-split` / `-guarded` pair is the same pattern for a
different import problem. This is the third instance of a shape this repository
already runs twice. `scripts/sync_vendor_source.py` is not in the cycle-16 mutation
proof's graded set, so adding a rule there retires no proof.

Worth recording for the next port: this repository filed upstream
`infiquetra/infiquetra-claude-plugins` #822 asking upstream to remove the fixed
`parents[3]` depth assumption from this exact file. Upstream fixed it by anchoring to
`.claude-plugin/plugin.json` — precisely the directory the port relocates away. A fix
that is correct upstream can still be unusable downstream. The port boundary is where
that shows up, and an upstream filing is not automatically the right answer to a
downstream break.

**Rejected alternatives.** *Hand-editing the byte copy* — the custody violation the
whole arrangement exists to prevent, and it fails its own digest check. *Dropping the
file from source the way `scripts/fleet_commons_shim.py` is dropped* — the shim was
dropped because the Fleet Core bundle replaces it, whereas nothing replaces this file,
and it is a declared entrypoint in both `assessment.entrypoints` and
`assessment.package_scripts`, so dropping it would silently shrink the package's
capability surface. *Filing upstream and stopping* — blocks the run for a defect that
is not upstream's to carry, since upstream's resolution is correct for upstream's own
layout.

**Revisit when** upstream adopts a layout-neutral package-root resolution that does
not hard-code a single marker directory. The transform can then retire and the file
can return to being a byte copy.


### Mission Control 2.15.2 resync: an inherited gate is met at a unit's completion, and three units complete in two commits

**Author.** Claude for Jeff Cox (Amendment 2 to the issue #50 run plan, repairing
doc-review cycle 3, branch `orch-agent-plugins-50`)

**Decision.** Two things, recorded together because the second only makes sense given
the first.

First, **ownership follows the issue, not convenience**: the `sync_template_docs.py`
custody work is split across the units that already own each file — the descriptor
reclassification to U1 (#52), the transform rule to U2 (#53), the rule's coverage to
U4 (#55). Amendment 1 had given all three to U2, which contradicted #53's own
out-of-scope section ("No edit to `ports/mission-control.json`"; "No downstream test
edits"). U1 has already landed and been accepted, so its share is a second commit
against the same unit rather than a rewrite of the first.

Second, **an inherited acceptance criterion is met at the unit's completion, not at
every intermediate commit**, and U1, U3, and U4 each complete in two commits so that
every unit's completion lands on a genuinely green tree. The landing sequence becomes
`U1a → U1b → U2 → U4a → U3a → freeze → U5 → U3b → U4b`.

**Rationale.** After the resynchronization, `python3 -m unittest discover -s tests` is
red on exactly two things: three pin constants in `tests/test_sync_vendor_source.py`,
owned by U4, and
`test_check_compatibility_matrix.LiveDocumentTest.test_the_no_argument_run_validates_every_committed_matrix`,
owned by U5. Three sibling issues — #54, #55, #56 — each require that command to report
`OK`, and each is blocked by the other's uncleared red. U4 needs U5's evidence re-bind;
U5 needs U4's pin fix *and* a final package, which does not exist until U3's
package-root edits land; U3 needs both.

The cycle is verified in code, not inferred. `check_package_binding` compares the
recorded `file_count` **and** `tree_sha256` against the live package, so any byte change
inside `plugins/mission-control/` invalidates a `matrix-status: current` document. And
`check_document_status` accepts a superseded stamp only when the named successor already
exists and is itself current, so a stale matrix cannot be retired before a fresh one is
published. No ordering of six single-commit units satisfies all three gates.

Splitting three units into two commits each costs nothing and narrows nothing. None of
the three issues says its gate must hold at every commit on the way to completion; each
says the command reports `OK`, and at each unit's final commit it does — with no
expected-red list, no moved checkpoint, and no weakened assertion. The deferred halves
are real deliverables, not bookkeeping: U3b carries the root README's counts, which can
only be finally correct once every unit has landed, and U4b carries the roster and
continuous-integration confirmations. Both are outside the package root, so neither
disturbs the freeze or invalidates the single ten-client assessment.

**Rejected alternatives.** *Naming `LiveDocumentTest` as an expected red in U3's and
U4's gates*, the way U2 names its pin constants — that is the narrowing an earlier
review finding already rejected, and #53 is the only child issue whose criteria permit
an expected-red list. *Moving the freeze before U3* — forbidden by #50's own text.
*Moving U3's package-root edits into U2* — contradicts #53's out-of-scope. *Running the
ten-client assessment twice, supersede-and-re-run* — legitimate under this repository's
evidence loop, and the agent-launcher port did exactly that when a repair moved its
tree, but a second operator-attended ten-client run is a real cost paid to avoid a
commit split that costs nothing; it stays the fallback if the split proves unworkable.
*Planting a dummy `.claude-plugin/` directory* so upstream's walk finds a marker — it
reintroduces the directory the port exists to relocate, makes a byte copy's behaviour
depend on a sibling file rather than its own bytes, inflates the fingerprint every piece
of evidence binds, and still fails for anyone who installs the documented layout without
it.

**Revisit when** a resynchronization has no target-owned edits inside the package root.
Then the freeze can follow the sync directly, the assessment has a final tree
immediately, and every unit can complete in one commit.


### Mission Control 2.15.2 resync: register a transform rule before anything names it, and six commits is provably unreachable

**Author.** Claude for Jeff Cox (Amendment 3 to the issue #50 run plan, repairing
doc-review cycle 4, branch `orch-agent-plugins-50`)

**Decision.** The new package-root transform rule is sequenced **registration first,
registry test second, descriptor third, synchronization fourth** — U2a, U4a, U1b,
U2b. And the run's landing shape is recorded as **eleven child-scoped commits, not
the six the run declaration assumes**, escalated to the operator as an explicit
question rather than absorbed as a compatible reading.

**Rationale.** Two committed tests fix the order, and neither is a plan choice.
`tests/test_port_config.py::CommittedDescriptorTest.test_every_entrypoint_transform_entry_names_a_rule_the_sync_tool_implements`
asserts that every rule a port descriptor names is present in
`sync_vendor_source.TRANSFORM_RULES`, so a descriptor edit that names an
unregistered rule fails the repository suite — which is exactly what the previous
amendment scheduled, claiming a reclassification "changes no behaviour on its own."
It does. `scripts/sync_vendor_source.py`'s `resolve_transform_rule` refuses the same
unregistered name, so `--check` would refuse too.

Correcting that surfaced a second constraint in the same area that neither the
amendment nor the review had reached:
`tests/test_sync_vendor_source.py::MissionShapedSyncTests.test_rule_names_register_exactly_once`
asserts `set(TRANSFORM_RULES)` equals a literal five-element set of name constants,
so registering a sixth rule fails it. That file belongs to U4 under #55, and #53
forbids U2 from editing downstream tests, so the registration and its registry
repair are two different units' commits by construction.

On the commit count: a six-commit shape was searched for before the deviation was
recorded, and it does not exist. Four prerequisites each force a split
independently — a descriptor may only name a registered rule; registering a rule
breaks a test another unit owns; the pin constants can only move after the
synchronization rewrites the provenance manifest; and the evidence can only be
re-bound after the last package-root edit, which is the unit whose own gate the
evidence unblocks. Add that #52, #54, #55 and #56 each require `unittest discover`
to report `OK`, and the minimum is eleven commits. The alternative to eleven is not
six commits; it is six commits plus three narrowed acceptance criteria, and
narrowing a gate is what an earlier review finding already rejected once.

The general rule worth carrying: **a registry and the data that selects from it are
joined by a test, so the writer of the registry entry must land before the writer of
the selection — even when the natural unit order runs the other way.** Ownership
decides *who* does a thing; a join test decides *when*.

**Rejected alternatives.** *Letting U2 register the rule and repair the registry test
in one commit* — contradicts #53's "No downstream test edits. U4 owns those."
*Letting U1 register the rule beside its descriptor edit* — contradicts #52's "This
unit changes the descriptor only." *Naming the red tests as expected in each unit's
gate* — the narrowing already rejected. *Running the ten-client assessment twice
under the supersede-and-re-run evidence loop* — legitimate, and the agent-launcher
port did exactly that, but it spends a second operator-attended session to save one
commit; kept as the fallback only if eleven commits is refused.

**Revisit when** a resynchronization introduces no new transform rule and makes no
target-owned edit inside the package root. Both join constraints and the freeze
constraint fall away together, and six commits becomes reachable.


### Mission Control 2.15.2 resync: the package-root transform is extended to rewrite what two carried tests assert

**Author.** Jeff Cox, recorded by Claude (Amendment 4 to the issue #50 run plan,
branch `orch-agent-plugins-50`). Operator decision; this entry records it and does
not implement it.

**Decision.** Extend the `resolve-package-root-marker` transform to a new version
whose shape covers, per file, the `_find_package_root` definition, its module-scope
call, **and the assertion sites** — the `.is_file()` marker assertions and the
`pytest.raises` error-text match — and reclassify
`plugins/mission-control/tests/test_issue_contract_parity.py` and
`plugins/mission-control/tests/test_template_sync.py` from `custody.byte_copies` to
`custody.entrypoint_transforms`.

**Rationale.** Both files carry upstream's `.claude-plugin/plugin.json` package-root
resolution and cannot work in the portable layout, where the Claude manifest is
relocated to `com.infiquetra.claude/`. Verified at pin `3b2b7083`: the contract-parity
test defines `_find_package_root` at line 36, raises at line 41, calls it at module
scope at line 46 so it fails at collection, and additionally asserts the marker on
itself at line 405 and pins the failure message at lines 410–417. The template-sync
test has no such function of its own — it exercises the module the earlier decision
already transforms — and two of its eight tests fail at lines 175 and 185–188
**because** that earlier transform changed the marker and the error text. The second
file is a consequence of the first decision, not an independent defect.

A scan of every `.py` file in the pinned package found the pattern in exactly six
files. Four positions were already settled: `fleet_commons_shim.py` dropped,
`sync_template_docs.py` transformed, `test_card_validator_agreement.py` dropped by
operator ruling, `test_prompt_alignment.py` dropped. These two were the only
unresolved ones, and there is no seventh. The scan is recorded in the plan so a future
resynchronization can re-run it rather than re-derive it.

**The cost, not softened.** This rule rewrites what a test *asserts*, not merely where
it looks. The earlier package-root decision deliberately stopped short of that line;
this one crosses it. A carried test whose assertions are rewritten downstream no
longer tests exactly what upstream tests, which is a real weakening of the
derived-artifact principle. The operator judged it acceptable because the alternative
was narrowing an inherited acceptance criterion — the whole reason the run accepted a
larger commit count — and because the rewritten assertion still asserts the same
property, that the package root is discoverable by this layout's marker, against the
marker this layout actually uses.

**The discipline that replaces single-shape.** The rule stops being single-shape,
which this repository's transform discipline resists. Four obligations replace that
guarantee: exact declared site counts per file; a loud refusal naming file, site class,
and counts on any mismatch, never a partial application; idempotence on already-portable
input; and reproducibility from the upstream bytes alone.

**Rejected alternatives.** *Drop both from source*, as two other tests are dropped —
the package would hold 69 files, breaking issue #53's explicit acceptance checkbox that
it holds 71, which is an inherited criterion the run's commit-count ruling was taken
specifically to preserve; and the portable copy would lose its contract-parity and
template-sync coverage. *File upstream and stop* — it does not complete the
resynchronization in this run and leaves the parent and all six children open pending
an upstream release on another schedule; upstream is not wrong for its own layout.
*Per-path rule parameters in `ports/*.json`* — carrying the per-file site counts in the
descriptor instead of the shared script would require a schema-4 bump of the closed
`{path, rule}` entrypoint-transform shape, and `scripts/port_config.py` is one of the
five cycle-16 graded files, so the bump was not taken in this run; the counts table in
the script is the cheaper shape, joined to the descriptor by a committed test in
`tests/test_port_config.py`. Revisit when a second rule needs per-path parameters, at
which point schema 4 earns its cost.

**Revisit when** upstream adopts a layout-neutral package-root resolution. Both of
these transforms and the earlier one should then retire, and all three files return to
being byte copies.


### A join test constrains exactly what it joins — and the Mission Control resync lands twelve commits, not thirteen

**Author.** Claude for Jeff Cox (Amendment 5 to the issue #50 run plan, repairing
doc-review cycle 6, branch `orch-agent-plugins-50`)

**Decision.** The package-root rule's v2 extension folds into the synchronization
commit instead of taking one of its own, so the run lands **twelve** child-scoped
commits rather than the thirteen the previous amendment recorded. And the plan's
claim that a custody-versus-provenance test constrained the descriptor
reclassification is **withdrawn**, because that test does not cover the package in
question.

**Rationale.** Both corrections come from the same mistake made in opposite
directions: reading "there is a join test here" as "therefore this ordering is
forced," without checking what the join actually joins or which fixture it loads.

The rule name `resolve-package-root-marker` has been registered since the run's first
synchronizer commit (`scripts/sync_vendor_source.py:102`, registry at line 855, pinned
in the expected set at `tests/test_sync_vendor_source.py:930`). The descriptor join,
`CommittedDescriptorTest.test_every_entrypoint_transform_entry_names_a_rule_the_sync_tool_implements`,
asserts `assertIn(rule, svs.TRANSFORM_RULES)` — it joins **names**, and no version
appears in it. So a descriptor may select that rule for two more paths while the rule
is still on v1. What v2 must precede is the synchronization run, because v1's
exactly-one-definition-plus-one-call shape would refuse a file that has neither. The
extension and the sync are one unit acting on one file, so they are one commit.

The second correction is the mirror image. The plan cited
`CommittedDescriptorTest.test_the_custody_table_accounts_for_every_shipped_managed_path`
as forcing the descriptor commit to gate on an already-transformed working tree. That
method reads `self.config`, and the class's `setUp` is
`port_config.load("unifi", ROOT)` — the docstring calls the UniFi descriptor "the
regression fixture for all of this." A mission-control reclassification cannot fail
it. A search for the test that *would* constrain it found none: nothing joins
mission-control's descriptor custody to its shipped provenance manifest, and
`check_repo.py` validates a manifest entry's own classification rather than comparing
it to the descriptor.

**Generalizable rule.** *A join test constrains exactly what it joins, over exactly
the fixtures it loads.* Before deriving a landing-order edge from a test, read two
things: which fields it compares, and what its `setUp` actually loads. In this run the
same unchecked inference invented a prerequisite once in the right direction and once
in the wrong one — costing an extra commit in the first case and putting a false
constraint into an accepted plan in the second.

**Rejected alternatives.** *Keeping the standalone extension commit* — defensible only
if some test forced it, and none does; an extra commit on a run already deviating from
its declared commit count needs a reason better than tidiness. *Re-pointing the
withdrawn caveat at a different test* — there is no other test to point it at, and
leaving a plausible-sounding constraint in place would have a worker gate on a
condition that does not exist.

**Revisit when** a second package's descriptor gains a custody-versus-provenance
binding, at which point the withdrawn caveat becomes a real constraint and should be
re-stated with the citation that then exists.


### Mission Control 2.15.2 resync U3a: the create-option reclassification is proven, not asserted, and the manifest version is derived, not retyped

**Author.** Claude for Jeff Cox (U3a of issue #50, child #54, branch `orch-agent-plugins-50`)

**Decision.** (1) Under operator ruling 4, `fields create-option` moves from
the mutating to the read-only set and `fields set-options` is added to the
mutating set, across the three locked surfaces in one commit —
`assessment.mutating_operations`, the portable README's per-skill verb table
(plus the prose sentence about the removed `rollout update`, dropped upstream
by filing #821), and `MUTATING_VERBS`/`READ_ONLY_VERBS` in
`tests/test_mission_control_readme.py`. Verified against the pinned source:
`fields_create_option` (sdlc_manager.py:2026) only discovers a field and
prints its options — its docstring states "This command performs NO mutation —
it never has" — while `fields_set_options` (2070) calls
`update_field_single_select_options` (2113), a real mutation unless `--dry-run`.
(2) Because reclassifying a verb from mutating to read-only narrows a safety
declaration, a focused guard now proves the mutation path is never reached:
`CreateOptionNoWriteGuardTests` drives `fields_create_option` through both the
happy and the absent-field error paths with `_graphql` patched and asserts the
destructive `QUERY_UPDATE_FIELD_OPTIONS` constant is never sent and no
GraphQL call occurs at all, in the style `test_option_identity.py` uses for
its error paths. The guard's negative proof was captured (deliberate
weakening went red, then reverted). (3) The manifest-version claim is closed
by derivation: `ManifestVersionDerivationTests` binds
`plugins/mission-control/plugin.json`'s `version` to `PROVENANCE.json`'s
`source_version` on the agent-launcher packaging-test pattern, so a
hand-edited manifest diverging from the provenance record fails.

**Rationale.** The #9 run's only review finding was a hand-transcribed
identity row with no derivation and no pin test; retyping the version
reproduces that defect one release later. A narrowed safety claim needs
positive proof rather than a changed constant — a test that merely asserts
the function returns without error proves nothing about writes.

**Rejected alternatives.** (a) Reclassify without a guard — a one-line
narrowing of a safety boundary with no evidence. (b) Leave `create-option`
mutating "to be safe" — over-declares, pollutes the audited table, and makes
the README's disclosure false in the other direction. (c) Retype the version
claim with reviewer discipline as the control — the exact failure the #9
review caught.

**Revisit when** upstream changes either handler's implementation, or a
future run retires the portable-README decision so the verb table no longer
lives in three locked places.

**Refs.** [`ports/mission-control.json`](../../ports/mission-control.json),
[`plugins/mission-control/README.md`](../../plugins/mission-control/README.md),
`tests/test_mission_control_readme.py`, `tests/test_mission_control_rule_audit.py`,
issue #54, operator ruling 4.

### Mission Control 2.15.2 resync U5: fresh evidence replaces the retired matrix and readback, and both replacements are bound

**Author.** Claude for Jeff Cox (U5 of issue #50, child #56, branch `orch-agent-plugins-50`)

**Superseded-run note.** This entry describes the FIRST 2026-08-30 assessment,
against tree `1f49322e…`. That tree was later retired by the F18/F11/F35
corrections, and the assessment was re-run against tree `659f91f6…` — see the
second-run entry immediately below. The entry is kept as the record of the
first run; its Qwen-failed outcome describes that run only, and its evidence
filenames were renamed when the repository's naming convention (plain name =
current) was restored.

**Decision.** The pre-resync mission-control compatibility matrix and
post-activation readback (both bound to 64 files / tree `651ac28a…`, v2.12.2)
are superseded by fresh records captured 2026-08-30 against the frozen
resynchronized package (71 files, tree `1f49322e…`, v2.15.2), each carrying a
`superseded-by` naming its successor and a `superseded-reason`; their recorded
numbers are untouched. Both replacements are bound in
`tests/test_check_compatibility_matrix.py` as parallel mission-control classes
(KTD4 — never parameterizing UniFi's live bindings): the matrix class
recomputes the live package fingerprint, name, and version and asserts them
against the record; the readback class asserts the `release` block, all seven
per-skill-unit fingerprints, `upstream_commit`/`version` against
`PROVENANCE.json`, and every readback entry — with no `profile_states`
assertions, because that block is a UniFi concept. The readback keeps a
`cycle_16_verification` block (KTD11): all five graded-file digests recomputed
at the new freeze still match the cycle-16 footer, so the block is a positive
statement that the resync retired no mutation proof. Qwen's assessment is
recorded `failed` with the honest reason: the isolated home's preserved Qwen
wrapper exited 127 on every stage, an environment condition, not a package
result. Both bindings were proven able to fail: a deliberate local
fingerprint mutation made them red (3 failures), then was reverted.

**Rationale.** The package fingerprint moved, which retired the old evidence;
the recorded decision forbids renumbering evidence that was not re-measured,
so the forty stage results had to be re-run rather than edited. The
supersession order (successor published current, only then the predecessor
stamped) is enforced by `check_document_status`, and the fresh run
reproduced the before/after fingerprint equality (71 files, `1f49322e…`)
that proves no client mutated its copy.

**Rejected alternatives.** (a) Renumber the old documents — exactly the
failure the bindings exist to catch: forty observed results would become
claims about bytes nobody ran. (b) Parameterize the UniFi binding classes —
puts UniFi's live bindings at risk for no gain. (c) Bind inside
`scripts/check_compatibility_matrix.py` — that file is in the cycle-16
mutation proof's graded set, and the bindings belong in the test file.

**Revisit when** the next resynchronization moves the fingerprint again, at
which point these bindings fire red until the evidence is re-run.

**Refs.** [`the first run's matrix, superseded by the second run`](../evidence/2026-08-30-mission-control-compatibility-matrix-pre-fingerprint-move.md),
[`the first run's readback, superseded by the second run`](../evidence/2026-08-30-mission-control-post-activation-readback-pre-fingerprint-move.md),
`tests/test_check_compatibility_matrix.py`, issue #56, operator ruling 3.

### Mission Control 2.15.2 resync U5 second run: the fingerprint moved under the F18/F11/F35 corrections, and the evidence was re-run rather than re-bound

**Author.** Claude for Jeff Cox (repair round 2 of issue #50, child #56, branch `orch-agent-plugins-50`)

**Decision.** When the F18/F11/F35 provenance and README corrections landed at
`a1e84e0`, the package moved from tree `1f49322e…` to tree `659f91f6…`, and
the first 2026-08-30 evidence pair stopped describing the shipped bytes. That
tree was itself retired one round later by the F71 beads-config disclosure
correction (`143a71b`), which moved the package to `5fc16652…` — see the
third-run entry immediately below for the current record. The
assessment was re-run (run-002) against the corrected package and published
as current — 3 clients work directly (Cursor Agent, Qwen, Agy), 7 work
through an adapter, 0 failed, 0 unsupported, no stage timed out — and both
replacements were re-bound in `tests/test_check_compatibility_matrix.py`.
Qwen's status changed from failed to works-directly because the run supplied
its real binary by exported override (`QWEN_HERDR_REAL_BIN`), exactly as
Grok's and Agy's were supplied by `--real-binary`: the earlier 127 reading
came from the wrapper resolving into the empty isolated home, not from the
package. The evidence filenames were later renamed so the current pair holds
the plain `2026-08-30` names and the retired pair carries the
`-pre-fingerprint-move` suffix, restoring the repository's convention that
the plain filename is always the current document.

**Why the fingerprint was allowed to move.** The three corrections were
judged more honest than the alternative: holding them back would have shipped
a provenance manifest whose own prose contradicted its files array (F18), a
README missing a disclosure its own commands depend on (F11), and an
unreconciled carried CHANGELOG (F35). The runbook's batch-the-repairs rule
applies: the three were batched into one round, one assessment re-run, one
new fingerprint — never a per-fix re-binding.

**Rejected alternatives.** (a) Holding the corrections back — ships the
self-contradicting provenance and the missing disclosure for the sake of the
first assessment's currency. (b) Editing the first-run evidence to match the
moved tree — the explicit anti-pattern; the numbers describe the bytes that
were actually assessed. (c) Re-binding without re-running — a bound digest
names the tree, not the stages that assessed it.

**Revisit when** a future round must edit any byte under
`plugins/mission-control/` after evidence is bound: the same batch-and-rerun
path applies, and the assessment must precede the stamping.

**Refs.** [`the second-run matrix, superseded by the third run`](../evidence/2026-08-30-mission-control-compatibility-matrix-pre-beads-config-ladder.md),
[`the second-run readback, superseded by the third run`](../evidence/2026-08-30-mission-control-post-activation-readback-pre-beads-config-ladder.md),
`tests/test_check_compatibility_matrix.py`, issue #56, operator ruling 3.

### The transform planner dispatches descriptor-level refusals through a precondition slot, not a hard-coded rule identity

**Author.** Claude for Jeff Cox (repair round 3 of issue #50, branch `orch-agent-plugins-50`)

**Decision.** `TransformRule` carries an optional `precondition` callable, and
`plan_sync` runs it before dispatching any path to the rule, so a rule whose
output depends on a descriptor value can refuse the synchronization at plan
time without widening the `apply` signature every rule shares.
`resolve-package-root-marker` attaches the marker-directory check through the
slot; the planner's loop no longer names any rule's identity.

**Rationale.** The previous shape tested `rule is PACKAGE_ROOT_MARKER_RULE`
inside the generic loop, compiling one rule's identity into the planner; the
slot keeps the loop dispatching on the abstraction and keeps the check beside
the rule it guards, in the same module.

**Rejected alternatives.** A per-rule subclass of `TransformRule` — more
machinery for one optional behaviour; a second dispatch table keyed by rule
name — reintroduces the hard-coded identity in another shape.

**Revisit when** a second rule needs a descriptor-level precondition, at which
point the slot is the established pattern.

**Refs.** `scripts/sync_vendor_source.py` (`TransformRule`,
`_package_root_marker_precondition`, `plan_sync`),
`tests/test_port_config.py` (`test_the_marker_precondition_refuses_a_mismatched_client_extension_dir`).

### Mission Control 2.15.2 resync U5 third run: the beads-config disclosure correction moved the fingerprint again, and the evidence was re-run again

**Author.** Claude for Jeff Cox (repair round 3 of issue #50, child #56, branch `orch-agent-plugins-50`)

**Decision.** Repair-round finding F71 showed the portable README claimed an
absent `beads-config.json` was handled locally when the loader in fact first
attempts a live `gh api` read of it from `infiquetra-sdlc` (and degrades to
`{}` only when that read fails or returns nothing). The README is
target-owned — this repository's own text — so the correction was authored
here at `143a71b`, moving the package from tree `659f91f6…` to tree
`5fc16652…` and retiring the second evidence pair. Per the now twice-applied
batch-and-rerun path, the assessment was re-run (run-003, 2026-08-31,
assessed_on stated in the body while the filename prefix keeps the
2026-08-30 family name, and the body says so plainly) and the evidence
re-bound: 3 clients work directly (Cursor Agent, Qwen, Agy), 7 work through
an adapter, 0 failed, 0 unsupported, no stage timed out. The Qwen disclosure
is carried forward verbatim: its real binary was supplied by exported
`QWEN_HERDR_REAL_BIN` exactly as Grok's and Agy's were by `--real-binary`,
the harness does not declare Qwen's override itself, and without it the
wrapper resolves into the empty isolated home and exits 127 — Qwen's
works-directly is not the package improving. The plain filenames hold the
current pair; every superseded generation carries a descriptive
`-pre-<reason>` suffix, and the three-generation chain resolves to the
current pair with no banner naming an already-superseded document.

**Rejected alternatives.** (a) Deferring the README correction to avoid a
third assessment — ships our own text describing behaviour the code does not
have, the same defect class as the F18 provenance prose. (b) Editing the
second-run evidence to match the moved tree — the explicit anti-pattern.

**Revisit when** the next resynchronization or repair round moves the
fingerprint: the same batch-and-rerun path applies a third time.

**Refs.** [`the superseded matrix`](../evidence/2026-08-30-mission-control-compatibility-matrix.md),
[`the superseded readback`](../evidence/2026-08-30-mission-control-post-activation-readback.md),
`tests/test_check_compatibility_matrix.py`, issue #56, operator ruling 3.


## 2026-08-27

### Auralis C3 adapter packaging: voice 0.3.0, mcpServers path into client extension, and acceptance evidence note

**Author.** Claude for Jeff Cox (Auralis C3 adapter U5 closeout, issue #46, branch
`orch/auralis-c3-adapter-build-c3-u5`)

**Decision.** Packaging for the Auralis C3 Claude adapter (`voice` 0.3.0) extends the Claude
packaging layout pinned on 2026-08-25: `plugins/voice/.claude-plugin/plugin.json` gains
`"mcpServers": "./com.infiquetra.claude/mcp/servers.json"` pointing to the server configuration
inside the client extension, keeping the packaging manifest pure distribution metadata
without command strings. Version is bumped to `0.3.0` across all four sites bound by
`tests/test_claude_plugin_packaging.py` (`plugins/voice/plugin.json`,
`plugins/voice/.claude-plugin/plugin.json`, `plugins/voice/com.infiquetra.claude/plugin.json`,
`.claude-plugin/marketplace.json`). Acceptance evidence for the nine C3 slice requirements is
captured in [`docs/evidence/voice/auralis-c3-acceptance.md`](../evidence/voice/auralis-c3-acceptance.md),
recording the five-route wire pin, the AE26 reject-then-accept proof across in-process and
declared-argv subprocess layers, and the joint AE36 cross-repository dependency on
`infiquetra/auralis`.

**Rationale.** Preserves the repository boundary rule (packaging manifest carries paths into
the client extension; behaviour and commands live under `com.infiquetra.claude/`). Four-site
version agreement prevents `claude plugin update` cache-staleness bugs. A dedicated
acceptance note keeps the Auralis V1 requirements namespace separate from the earlier 0.2.x
voice ledger.

**Rejected alternatives.** Inline `mcpServers` object in the packaging manifest (violates
metadata-only manifest rule); bumping version at only some sites (fails packaging test);
merging C3 evidence into the 0.2.x `acceptance.md` (collides the two R-ID numbering schemes).

**Revisit when.** Claude Code changes plugin MCP server manifest resolution, or the Auralis
Bridge Contract v2 merges.

**Refs.** [`docs/plans/2026-08-27-auralis-c3-adapter.md`](../plans/2026-08-27-auralis-c3-adapter.md),
[`docs/evidence/voice/auralis-c3-acceptance.md`](../evidence/voice/auralis-c3-acceptance.md),
`tests/test_claude_plugin_packaging.py`.

### Auralis C3 plan repair: a tracked byte-pinned wire snapshot, a locked turn-record transaction, and a gate-owned rejected-syntax contract

**Author.** Claude for Jeff Cox (Auralis C3 plan repair against the blocking doc review,
issue #46, branch `orch/auralis-c3-adapter-plan-c3-repair`)

**Decision.** The repair of
[`docs/plans/2026-08-27-auralis-c3-adapter.md`](../plans/2026-08-27-auralis-c3-adapter.md)
(doc-review findings F1–F12, disposition table at the plan's end) fixes four load-bearing
choices. First: the wire contract is pinned by a **tracked byte-identical snapshot**
([`docs/bridge-v1-from-c10.md`](../bridge-v1-from-c10.md)) of
`docs/bridge/bridge-v1.md` in `infiquetra/auralis` at accepted revision
`695cd0ecfddf44e0d6e3386da318bd5fde4a1926`, SHA-256
`eb47d141e5c1b87bae0bd1c0799386a3aa8806635251db14fc806469b5db19eb` — a clean checkout and
the hosted CI must resolve the plan's links without reading another repository's unmerged
branch, and byte-identity keeps the pin hash-verifiable. Second: the shared per-turn
record is mutated only through one `fcntl.flock`-serialized read-apply-write entrypoint
(plan KTD11); atomic write-replace is only the torn-write defense, because whole-file
replacement cannot prevent two writers from erasing each other's updates. Third: the R121
rendering gate owns a complete, closed rejected-syntax contract (setext headings,
reference links, autolinks, indented code included) rather than inheriting the speak-path
cleanup recognizers, whose documented scope is narrower than Markdown. Fourth: the two
Herdr identity values the bridge contract mandates are read through `settings.py`'s
extended closed `SETTING_NAMES` set, preserving the package's sole-environment-reader
rule instead of adding a second reader.

**Rejected alternatives.** An external permalink as the only wire pin (CI and clean
implementation checkouts cannot resolve it); deleting the contract reference (the plan
must stay traceable to a specific revision); `O_CREAT|O_EXCL` lock files (crash-stale
locks need their own cleanup protocol) and SQLite (disproportionate to one single-turn
JSON document); "one writer per field family" as a concurrency claim (the reviewed
lost-update defect); direct environment reads in `adapter_identity.py` (breaks the stated
sole-reader contract).

**Revisit when.** The C10 contract merges to `auralis` main (the snapshot then re-pins to
the merged revision), the turn record outgrows a single turn, or a bridge v2 changes the
wire.

### Auralis C3 adapter plan: the R121 gate lives in the adapter surface, and the MCP server is the adapter's long-lived process

**Author.** Claude for Jeff Cox (Auralis C3 planning, issue #46, branch
`orch/auralis-c3-adapter-plan-c3-adapter`)

**Decision.** The plan at
[`docs/plans/2026-08-27-auralis-c3-adapter.md`](../plans/2026-08-27-auralis-c3-adapter.md)
extends the voice package into the Claude adapter end of the Auralis local bridge, with
two load-bearing choices and eight supporting ones (KTD1–KTD10 in the plan). First: the
plain-spoken-text rule (Auralis requirement R121) is enforced in the adapter's Model
Context Protocol submission tool, not on the wire — the bridge contract's adjudication
vocabulary carries no content-form reason, Core accepts text verbatim, and the tool
answers with a three-class result vocabulary (adapter content rejections
`fenced_code_block` / `markdown_formatting`, Core rejections relayed verbatim, and named
availability conditions), never a cleaned rewrite. Second: the plugin-declared MCP stdio
server is the adapter's one long-lived process, so the bridge presence-renewal loop lives
in it, while every Claude hook stays an ephemeral one-shot client; submissions target the
`(binding_id, turn_id)` pair captured at prompt time, never a fresh snapshot at
submission time.

**Rationale.** The agent-facing surface is the only place R121 *can* live without a
cross-lane wire change; splitting the reason vocabulary keeps adapter judgment, Core
judgment, and availability impossible to confuse. Plugin MCP servers persist for the
session (verified against current Claude Code documentation), which meets the lease
cadence no hook process can hold; the prompt-time pair makes Core's own
`turn_not_current` adjudication the arbiter of staleness instead of silently retargeting
a late rendering.

**Rejected alternatives.** Repairing submissions with the existing cleanup pass (R121
forbids repair); asking C10 for a wire-level content reason (Core custody); a separate
presence daemon (new lifecycle surface, nothing needs it); fresh identifier reads at
submission (wrong-turn hazard); an inline `mcpServers` object in the Claude packaging
manifest (a command in a metadata-only file — the declaration is a string path into
`com.infiquetra.claude/` instead).

**Revisit when.** A bridge v2 adds content adjudication or changes identifier custody, or
the Claude client changes plugin MCP-server lifecycle. The full per-decision revisit
conditions are in the plan's KTD section.
### The agent-launcher port carries the contract as a byte copy and supersedes the Claude-runtime docs

**Author.** Jeff Cox and Qwen Code (issue #22, branch `port/agent-launcher`,
run plan `docs/plans/2026-08-27-agent-launcher-port-plan.md`, runbook v1.1.0)

**Decision.** The accepted upstream plugin's launch contract
(`skills/agent-launcher/scripts/launcher.py`) is pure standard library and
vendor-gated, so it lands as an unmodified upstream byte copy — its Claude
account-verification block is explicit documented behavior for `vendor ==
"claude"`, not a vendor-specific hidden path, and forking the bytes downstream
is barred by the custody rule. The upstream `SKILL.md` and `README.md` are
superseded by target-owned portable docs rather than carried: the upstream
skill resolves its script through `CLAUDE_PLUGIN_ROOT` with a fallback ladder
into the Claude plugin cache, and carrying those bytes would be the exact
"copy Claude-specific behavior" failure the port exists to avoid. The upstream
test suite is dropped with a recorded reason (its remaining premises —
Orchestrate ingestion, the root marketplace, `parents[3]` repo-root
resolution — cannot cross the port boundary), and the portable suite under
`plugins/agent-launcher/tests/` re-proves the portable contract from
`parents[1]`. The assessment declares no credential prefixes (the launcher
reads no credentials) via `declared_none`, names `launch` and `close` as its
mutating verbs so the harness blocks them, and keeps no marketplace entry:
catalog distribution stays withheld pending an operator decision, locked by a
packaging test. The ten-client matrix records 7 clients working directly, 3
through an adapter, none failed, bound to the package fingerprint with a
post-activation readback; evidence is content-bound, and an accepted repair
that moves the fingerprint supersedes the record rather than renumbering it.

**Refs.** [`ports/agent-launcher.json`](../../ports/agent-launcher.json),
[`plugins/agent-launcher/CHANGELOG.md`](../../plugins/agent-launcher/CHANGELOG.md),
[the compatibility matrix](../evidence/2026-08-27-agent-launcher-compatibility-matrix.md),
[the run plan](../plans/2026-08-27-agent-launcher-port-plan.md)

## 2026-08-25

### Claude installs the package root; the client extension keeps the behaviour

**Author.** Jeff Cox and Claude (Voice packaging follow-up, branch
`orch/voice-claude-packaging`)

**Decision.** The Claude Code distribution of a package in this catalog is the
*package root*, not its `com.infiquetra.claude/` client extension. For `voice`
that means `.claude-plugin/plugin.json` sits at `plugins/voice/`, the
repository carries a Claude marketplace at `.claude-plugin/marketplace.json`
whose entry names `./plugins/voice` as its source, and the Claude manifest
declares every component by path into the client extension
(`"hooks": "./com.infiquetra.claude/hooks/hooks.json"`) rather than holding any
behaviour itself. `plugins/voice/plugin.json` is untouched and remains the
portable Agent Plugins manifest.

**Rationale.** Two facts about the installed Claude CLI (2.1.246) decide this,
and neither is visible from the repository:

1. Claude resolves a plugin only at `<root>/.claude-plugin/plugin.json`. There
   is no fallback to `<root>/plugin.json`, so the extension's portable manifest
   read to the CLI as no manifest at all: `claude plugin validate
   plugins/voice/com.infiquetra.claude` failed with "No manifest found in
   directory."
2. An install copies exactly the directory a marketplace entry's `source`
   names, and nothing above it. Verified by installing a probe marketplace and
   reading the cache.

The Stop hook imports the portable core and spawns `scripts/speak.py` from it,
resolving both with `Path(__file__).resolve().parents[2]`. Installing only the
extension would therefore copy the hook without the core it calls: the plugin
would install and validate cleanly, then fail at the first spoken response. A
probe install proved the chosen layout resolves that path correctly inside the
cache and that Claude registers both the Stop hook and the Voice skill from it.

**Rejected alternatives.** Duplicating or vendoring the portable core inside
the client extension (this catalog does not keep a second writable copy of a
package, and the operator ruled it out). Pointing the hook at a checkout via an
environment variable (an installed plugin that silently depends on a working
tree at a known path is not installed). Relying on the marketplace entry's
inline metadata alone — that does validate the *marketplace*, but `claude
plugin validate plugins/voice` still fails without the manifest, and the
package must validate on its own.

**Consequence for the repository boundary.** `CLAUDE.md` says Claude-specific
marketplace metadata belongs in an explicit Claude adapter. These two files are
the exception the CLI's contract forces, and the exception is narrow on
purpose: both are pure distribution metadata that name paths and hold no
command, hook body, agent, or permission. Every Claude *behaviour* remains
inside `com.infiquetra.claude/`. `tests/test_claude_plugin_packaging.py`
enforces both halves — that the manifests exist where Claude looks, and that no
`hooks/`, `agents/`, or `commands/` directory appears at the portable root.

**Revisit when.** Claude Code supports a manifest location other than
`<root>/.claude-plugin/`, or a marketplace source that installs a directory
while rooting the plugin beneath it. Either would let the packaging manifest
move inside the adapter with no other change.

### Voice plugin version one: one run-wide plan, seven units, acceptance with recorded findings

**Author.** Jeff Cox and Qwen (orchestrated run `orch-2026-08-25-voice`, U7
closeout, [#34](https://github.com/infiquetra/infiquetra-agent-plugins/issues/34))

**Decision.** The `voice` package was built as seven units (U1–U7, issues
#28–#34) from one run-wide implementation plan with exact-once ownership of
requirements R1–R33 and a closed four-lane dependency graph; backend `inline`
for every unit with external orchestration supplying pools and gates. U7 ran
the R33 acceptance against the live deployment and recorded the results —
conditional pass with nine numbered findings — in
[`docs/evidence/voice/acceptance.md`](../evidence/voice/acceptance.md). This
closeout mirrors the plan's KTD1–KTD16 into the entries below, all of which
survived contact with implementation; the findings record where the live
environment diverged from a probe contract without changing a KTD.

**Rationale.** A single plan preserved the contract's unit boundaries,
shared-file collision rules, and exact-once requirement ownership across
seven worker sessions; running acceptance against the real Voice Forge and
Hermes deployment — rather than the hermetic fakes the suite requires — is
what surfaced four contract drifts no unit test could see.

**Rejected alternatives.** Per-unit plans (would re-fragment the cross-unit
contracts the parent settled); accepting on the hermetic suite alone (would
have shipped preflight probes that fail against the deployed services).

**Revisit when.** The acceptance findings (F1–F9 in the evidence file) are
scheduled for repair, or an attended pass covers the two human-shaped gaps
(live voice input; the blocked-state refusal branch).

**Refs.** Parent #27, children #28–#34,
[run plan](../plans/2026-08-25-voice-plugin-implementation-plan.md),
[requirements](../brainstorms/2026-08-25-voice-plugin-requirements.md),
[`docs/evidence/voice/acceptance.md`](../evidence/voice/acceptance.md).

### Voice state lives in machine-local JSON files, and the Claude Stop hook detaches (KTD1, KTD2)

**Author.** Jeff Cox and Qwen (voice run U7 closeout, #34)

**Decision.** Runtime state is one machine-local directory (default
`~/.local/state/voice`, overridable via `VOICE_STATE_DIR`) shared between the
`Stop` hook and the Voice pane through small JSON files written
temp-then-`os.replace`: `binding.json`, `recording.json`, `playback.json`, a
single current `refused-transcript.txt`, and unique per-spawn
`speak-<uuid>.json` payload files. No daemon. The hook does exactly four
things — read the payload from stdin once, compare `session_id` against the
binding with a local file read, write the payload file when bound, spawn
`speak.py` as a fully detached child (new session, stdin closed, streams to
devnull) — and exits 0 immediately. The harness timeout in `hooks.json` is a
backstop, not a budget; every hook path, including malformed input, exits 0.

**Rationale.** Claude Code runs `Stop` hooks synchronously — measured on this
host: a blocking 8 s hook delayed turn settle by 8.19 s while a detaching
hook returned in 0.030 s (see the LEARNINGS entry). The non-goals exclude any
resident daemon; one operator makes file-granularity coordination sufficient;
`~/.local/state` survives reboots, which sticky binding requires. Live
acceptance measured hook returns of 0.04–0.05 s while children spoke for up
to ~40 s.

**Rejected alternatives.** Repo-relative state (worktrees multiply it);
`/tmp` (cleaned by the OS; the binding must persist); sockets or a daemon
(machinery without a requirement); the response text on the child's stdin
(R32 closes stdin) or as an argv element (long replies must not meet
`ARG_MAX`).

**Revisit when.** Version one's non-goals change — a resident listener,
multi-session arbitration, or a second hook needing the same seam.

**Refs.** [plan](../plans/2026-08-25-voice-plugin-implementation-plan.md)
KTD1/KTD2, `plugins/voice/com.infiquetra.claude/hooks/stop_hook.py`,
`plugins/voice/scripts/binding.py`,
[`docs/evidence/voice/acceptance.md`](../evidence/voice/acceptance.md) AE1.

### Voice deadlines derive from the medium, never from the text (KTD3)

**Author.** Jeff Cox and Qwen (voice run U7 closeout, #34)

**Decision.** Every subprocess Voice starts carries closed stdin and a
deadline, pinned by class so workers never invent numbers: bounded helper
calls (`herdr agent get`, `herdr pane send-text`) 10 s; playback deadline =
the synthesized wav's actual duration (stdlib `wave` header read) plus 2 s
margin; capture recorder `ffmpeg -t 600` as both media ceiling and deadline;
the detached speak child carries its deadlines internally (10 s connect,
300 s read for synthesis, then the duration-derived playback deadline). A
deadline that passes is a named refusal — never truncation, never a shortened
utterance.

**Rationale.** R5 forbids any length gate; deriving the playback deadline
from the audio's own duration is what lets a long reply get a long deadline
and be spoken whole. Acceptance spoke a 75-word reply through a continuous
~28–30 s playback window with no deadline firing in any success path.

**Rejected alternatives.** Fixed playback timeouts (truncate long replies);
deadlines scaled from character count (a length gate by another name).

**Revisit when.** A streaming synthesis backend replaces whole-wav responses
and the "duration known before playback" assumption goes with it.

**Refs.** [plan](../plans/2026-08-25-voice-plugin-implementation-plan.md)
KTD3, `plugins/voice/scripts/process.py`, `plugins/voice/scripts/speak.py`,
`plugins/voice/scripts/record.py`.

### Closed egress set with external as predicate; declarations built in code; stated settings (KTD4, KTD5, KTD6)

**Author.** Jeff Cox and Qwen (voice run U7 closeout, #34)

**Decision.** The egress class is exactly R21's four literals — `on-device`,
`local-network`, `named-remote-service`, `unofficial-remote-endpoint` — and
"external" is the predicate over that set true for the two remote classes,
never a fifth value. `providers.py` builds exactly two declarations from the
stated settings (`voice-forge`, text-to-speech, `local-network`;
`hermes-xai`, speech-to-text, `named-remote-service`), each carrying
invocation-or-endpoint, capabilities, egress class, and the *name* of any
credential environment variable — both credential names empty, because Hermes
owns the upstream credential and the loopback session token is a transport
detail. There is no provider config file in version one. `settings.py` is the
one settings reader: stated names, split defaults (`VOICE_FORGE_*` carry
none), absent never treated as empty, no setting carries a secret, and
`VOICE_RETENTION` accepts exactly `ephemeral`.

**Rationale.** The speech-to-text route is external even though its transport
is loopback — Hermes is transport, xAI is the named service, and a loopback
address never downgrades the class; writing `external` as an enum value would
have broken the closed set. Both providers are settled operator decisions
(D1/D2), so a config registry buys nothing until a third provider exists.

**Rejected alternatives.** A `providers.toml`/JSON registry (revisit when a
provider beyond D1/D2 is actually declared); `external` as a fifth egress
value; silent defaults for deployment-specific settings (a default base URL
would hard-code a deployment).

**Revisit when.** A third provider is actually declared (then: the config
file); acceptance finding F7 is scheduled — no runtime path consults
`retention()` yet, so a mis-stated posture is silently ignored rather than
refused by name.

**Refs.** [plan](../plans/2026-08-25-voice-plugin-implementation-plan.md)
KTD4/KTD5/KTD6, `plugins/voice/scripts/providers.py`,
`plugins/voice/scripts/settings.py`,
[`docs/evidence/voice/acceptance.md`](../evidence/voice/acceptance.md)
findings F3/F7.

### Bind-time single-speaker join; delivery refuses blocked agents audibly and holds the transcript (KTD7, KTD11)

**Author.** Jeff Cox and Qwen (voice run U7 closeout, #34)

**Decision.** `bind` resolves the chosen Herdr agent once through `herdr
agent get` and stores agent name, Claude session id, and pane id; the binding
is single-valued and sticky, changing only on explicit rebind. The hook
compares its payload's `session_id` against the stored value with a pure
local read — no `herdr` call on the hot path. Delivery re-resolves pane id
and `agent_status` at send time; a `blocked` agent receives nothing — the
refusal is spoken through the speak path and the transcript is held in one
current file (replaced, never appended) until the operator explicitly uses or
discards it. Otherwise the transcript is whitespace-normalized to a single
line and sent with `herdr pane send-text` — literal text, no Enter, never
`herdr pane run`. Only the bound agent is ever targeted. The check-then-send
race is the contract's stated residual: narrowed by checking immediately
before send, deliberately not closed here.

**Rationale.** Keystrokes to a blocked agent are choices, not text (R18);
single-line normalization eliminates newline-as-Enter without escaping games;
the guard belongs to Herdr's delivery command as a proposed enhancement, and
no workaround machinery is built in the plugin.

**Rejected alternatives.** Focus or recency inference for the target;
queueing or auto-retrying refused transcripts; escaping games for newlines;
race-closing machinery inside `voice`.

**Revisit when.** Herdr ships a guarded `send-text` — the residual closes at
the right layer and the proposal should be filed upstream.

**Refs.** [plan](../plans/2026-08-25-voice-plugin-implementation-plan.md)
KTD7/KTD11, `plugins/voice/scripts/deliver.py`,
`plugins/voice/scripts/binding.py`,
[`docs/evidence/voice/acceptance.md`](../evidence/voice/acceptance.md)
AE1/AE8 and finding F4.

### Provider wire contracts: wav synthesis with duration-derived playback; data_url transcription with one refresh and one retry; synthesized preflight sample (KTD8, KTD9, KTD15)

**Author.** Jeff Cox and Qwen (voice run U7 closeout, #34)

**Decision.** `speak.py` POSTs the OpenAI-compatible body — `input`, `voice`,
`response_format: wav` — plays the response through the operator-stated
player under the duration-derived deadline, records `playback.json` for stop
and barge-in, and deletes the audio on every exit path. `transcribe.py` holds
the loopback session token in process memory only — never persisted, printed,
logged, or carried in an argument — and POSTs `{"data_url":
"data:audio/wav;base64,..."}` with the `X-Hermes-Session-Token` header; on
401 it refreshes the token from the root page once and retries once, never a
loop; it consumes `transcript` and `provider` (a provider other than `xai`
is a named refusal), ignores `ok`, and deletes the wav on every path.
Preflight proves the speech-to-text route with a short synthesized sample
rather than a bundled binary or a fresh microphone recording.

**Rationale.** The field names are the live relay's wire contract, verified
against the acceptance relay (v0.20.4) before and during this run — not an
invention; the live round trip returned the phrase verbatim with `provider:
xai`. Refusing a mismatched provider rather than substituting keeps R23
absolute.

**Rejected alternatives.** Invented request fields (`audio`, `file`,
`content`); retry loops around the 401 refresh; a committed wav fixture
(binary in a text-audited package); a mic-coupled probe (couples the STT
proof to the microphone grant).

**Revisit when.** The relay's request or response shape changes; acceptance
finding F3 is scheduled — the relay's silence mapping omits `provider`,
which the guard currently surfaces as a mismatch refusal instead of a quiet
"nothing to deliver".

**Refs.** [plan](../plans/2026-08-25-voice-plugin-implementation-plan.md)
KTD8/KTD9/KTD15, `plugins/voice/scripts/speak.py`,
`plugins/voice/scripts/transcribe.py`, `plugins/voice/scripts/preflight.py`.

### Markdown cleanup strips formatting and omits fenced contents; parses nothing fancy (KTD10)

**Author.** Jeff Cox and Qwen (voice run U7 closeout, #34)

**Decision.** `text_cleanup.py` is a small line/regex pass: fenced code
blocks (backtick and tilde) go contents-and-fences first, then formatting
syntax is stripped so it is not spoken — headings, emphasis/strong markers,
list and blockquote markers, horizontal rules, link syntax (keep the text,
drop the URL), inline-code backticks, table pipes. No length gate, ceiling,
truncation, sentence parsing, or summarisation exists anywhere on the path;
fidelity beyond the tested classes is explicitly not a version-one goal.

**Rationale.** R5–R7 need the formatting gone and the fenced contents
omitted; a real Markdown parser carries weight the requirement does not ask
for, and the observed live cleanup of a reply carrying bold, a link, and a
fenced function spoke exactly the prose and nothing else.

**Rejected alternatives.** A real Markdown parser; any form of truncation or
sentence budget.

**Revisit when.** Spoken-formatting fidelity becomes an actual operator
complaint rather than an assumed one.

**Refs.** [plan](../plans/2026-08-25-voice-plugin-implementation-plan.md)
KTD10, `plugins/voice/scripts/text_cleanup.py`,
[`docs/evidence/voice/acceptance.md`](../evidence/voice/acceptance.md)
R6/R7 rows.

### Hermetic seams everywhere, read-only keybinding probe, authored-here identity, pane as lazy-import sequencer (KTD12, KTD13, KTD14, KTD16)

**Author.** Jeff Cox and Qwen (voice run U7 closeout, #34)

**Decision.** No unit test may touch the network, spawn a platform binary, or
shell out to `herdr`: HTTP goes through an opener seam per module,
subprocesses through the runner seam, paths through `VOICE_STATE_DIR`.
`plugins/voice/tests/` ships no `__init__.py` so the shared pytest process
keeps one `tests` package, and the voice test basenames and script module
names collide with nothing collected. The R14 keybinding preflight reads
Herdr's `config.toml` read-only and reports absence by name; voice never
writes any Herdr configuration. The package carries no `PROVENANCE.json`, no
port descriptor, and no `CHANGELOG.md`, and its README states that plainly.
The pane is the listen-path sequencer and the only long-running process; it
imports `deliver` only inside the key handler through an injectable seam, and
same-lane units never import each other at module level.

**Rationale.** CI's ubuntu runners have no `afplay`, no AVFoundation device,
no Herdr, and no live providers, so real-world behaviour is proven by
preflight and acceptance instead of unit tests; mission-control already
claims the top-level `tests` package name in the shared pytest process; R15
and R30 are structural, not aspirational; U5 and U6 dispatched concurrently.
The CI glob collected 509 plugin tests in one process at the final commit
with no namespace collision.

**Rejected alternatives.** An `__init__.py` in voice tests (shadows the
claimed package); a curses or third-party TUI; module-level imports across
the G3 lane boundary.

**Revisit when.** A future package reuses a voice module name (CI catches
it); first external release (then: the changelog).

**Refs.** [plan](../plans/2026-08-25-voice-plugin-implementation-plan.md)
KTD12/KTD13/KTD14/KTD16, `plugins/voice/scripts/preflight.py`,
`plugins/voice/scripts/pane.py`, `plugins/voice/README.md`.

### Async worker watchers trigger on branch commits and runner liveness, never agent status

**Author.** Jeff Cox and Claude (mission-control migration retrospective,
[#9](https://github.com/infiquetra/infiquetra-agent-plugins/issues/9))

**Decision.** A watcher over a dispatched CLI-agent unit wakes on durable side
effects — a commit appearing on the unit's branch, or its runner process dying —
with agent status used only as a long-threshold stall signal that the agent's
own heartbeat resets. Status alone never triggers action.

**Rationale.** Antigravity reports `done` at its async turn boundary while a
background runner keeps executing; the mcport-9-resume1 run burned three watcher
redesigns on this (a 5-minute idle alarm fired mid-work twice) before the
commit-triggered design held for the rest of the run.

**Rejected alternatives.** Status-polling watchers (false alarms by
construction); short idle thresholds without heartbeat reset (fire during any
long grind, such as a 47-minute mutation-anchor run).

**Revisit when.** A driven CLI exposes a first-class completion signal distinct
from its conversational turn state.

### Record-only orchestration branches are marked merge=false at creation

**Author.** Jeff Cox and Claude (mission-control migration retrospective, #9)

**Decision.** Any orchestrate unit whose branch exists to be read rather than
landed — a review controller, a doc-review unit, a unit that stopped on a
blocked marker — carries `merge=false` in the run state, set the moment its
nature is known.

**Rationale.** `land` merges every done unit with commits and applies no review
or content gating in selection. When the first U8 evidence unit stopped by
committing `.orchestrate-unit-blocked.md`, only an immediate `merge=false` edit
kept the blocked marker off the integration lane.

**Rejected alternatives.** Land-time vigilance (one missed `land` ships the
marker); deleting the blocked branch immediately (destroys the record before its
content is durably quoted into the child issue).

**Revisit when.** Orchestrate grows a first-class record-only unit type.

### Portable mission-control package port executed under runbook v1.0.0 (U9)

**Author.** Jeff Cox and Antigravity (orchestrated unit U9, issue #19)

**Decision.** The mission-control package port followed
[porting runbook v1.0.0](../runbooks/portable-plugin-port.md) across all four
phases without inventing new moving parts or diverging from the runbook
workflow: Phase 0 setup and descriptor configuration, Phase 1 synchronization
and transforms, Phase 2 bundling and rule audit, and Phase 3 frozen evidence
collection and multi-client assessment. The ten-client compatibility
assessment ([the 2026-08-25 matrix, superseded by the 2.15.2 re-assessment](../evidence/2026-08-25-mission-control-compatibility-matrix.md))
recorded 1 works-directly (Agy), 8 works-through-an-adapter (including 4
skill-scoped clients that fully consume the 7 skills), 1 failed (Cursor Agent
relocatability finding on `sync_template_docs.py`), and 0 unsupported.
Following the established pilot precedent ([`DECISIONS.md`](#pause-the-pilot-at-the-compatibility-matrix-and-take-no-client-specific-remediation), 2026-08-22),
work stops at the completed matrix with no downstream patches to copied content;
remediations are filed upstream.

**Rationale.** Stopping at the completed matrix preserves the single-source-of-truth
and provenance custody guarantees. A downstream fix to copied content would turn
this catalog into an uncoordinated fork. Recording the matrix results and
filing upstream issues keeps derivation clean and reproducible.

**Rejected alternatives.** Repairing `sync_template_docs.py` downstream before
publishing evidence (violates custody discipline); creating client-specific
entrypoint adapters during the port (remediation is a separate operator decision).

**Revisit when.** Upstream ships fixes for the filed issues and a re-synchronization
is authorized, or the operator authorizes client-specific adapter work.

**Refs.** Child #19, [run plan U9](../plans/2026-08-24-mission-control-port-run-plan.md),
`docs/runbooks/portable-plugin-port.md` v1.0.0,
`docs/evidence/2026-08-25-mission-control-compatibility-matrix.md`,
`docs/evidence/2026-08-25-mission-control-post-activation-readback.md`,
`docs/evidence/2026-08-25-cycle16-mutation-proof-portable-copies.txt`.

---

### Fleet bundle schema version 2: data file bundling via verbatim byte copying (U5)

**Author.** Jeff Cox and Antigravity (orchestrated unit U5, issue #15)

**Decision.** `schemas/fleet-bundle.schema.json` is extended to version 2 by
adding an optional top-level `data` array for non-Python data file assets
(e.g., `models.json`). `scripts/bundle_fleet_module.py` and `scripts/check_repo.py`
handle data files via verbatim byte copying with no comment stamp blocks, and
enforce freshness via direct byte-equality against the Fleet Core source asset.
Schema version 1 declarations remain valid and byte-untouched for UniFi.

**Rationale.** Non-Python data formats like JSON cannot accept Python comment
stamps (`# Generated by...`) without violating their file syntax and failing
parsers. Verbatim byte copy with byte-equality checking preserves JSON format
validity while guaranteeing that bundled data assets match the Fleet Core source
digest pinned in `PROVENANCE.json`.

**Rejected alternatives.** Injecting synthetic JSON comment keys (breaks schemas
that enforce `additionalProperties: false`); wrapping data files in Python modules
(unnecessary indirection when consumers expect direct JSON assets); migrating
existing UniFi declarations to schema version 2 (unnecessary churn that moves
UniFi's fingerprint).

**Revisit when.** A non-Python data format requires templated transformation or
interpolation at bundle time.

**Refs.** Child #15, [run plan U5](../plans/2026-08-24-mission-control-port-run-plan.md),
`schemas/fleet-bundle.schema.json`, `scripts/bundle_fleet_module.py`,
`scripts/check_repo.py`, `tests/test_fleet_bundle_schema.py`,
`tests/test_bundle_fleet_module.py`.

---

## 2026-08-24

### Ported test suite custody, CI glob execution, and generalized entrypoint enforcement (U6)

**Author.** Jeff Cox and Antigravity (orchestrated unit U6, issue #16)

**Decision.** Five test-custody and verification contracts for ported packages:
(1) Carried upstream test suites live inside the package tree under
`plugins/<package>/tests/` (twenty-one files for mission-control, 266 tests),
verified conftest-independent with zero repo-root `conftest.py` files.
(2) Continuous integration's floor-pinned `plugin-tests` job
(`.github/workflows/ci.yml`) targets the `plugins/*/tests` glob, installs
`pyyaml` (`python -m pip install --upgrade pip requests urllib3 pyyaml pytest`),
and removes exit-status-5 masking so empty test collections fail.
(3) `tests/test_client_entrypoints.py` generalizes across all descriptors in
`ports/*.json` via `port_config.load_all()`, drives declared
`assessment.entrypoints`, strips declared `credential_prefixes`
(`GH_`/`GITHUB_` for mission-control, `UNIFI_` for unifi), preserves
bundle-deletion controls, and skips (not fails) entrypoints whose uninstalled
third-party dependencies (such as PyYAML) are absent in hermetic test runs.
(4) `tests/test_python_floor.py` `DECLARATION_SITES` adds
`plugins/mission-control/README.md` (`python>=3.12`);
`plugins/mission-control/CHANGELOG.md` is an immutable upstream byte copy under
provenance custody (pinned at `84eaf042`) so unlike target-owned
`plugins/fleet-core/CHANGELOG.md` it is excluded from declaration sites.
(5) `tests/test_check_repo.py` gains a survivor-killing test for missing Fleet
Core data-file sources in `check_bundled_files`, plus a meta-check confirming CI
globs match on-disk plugin test suites.

**Rationale.** Placement inside the package puts every test under `PROVENANCE.json`'s
closed set and `check_repo.py`'s manifest validation. Using `plugins/*/tests` in CI
with exit-status-5 masking removed ensures no ported package can silently skip
its test suite. Iterating descriptors dynamically in `test_client_entrypoints.py`
prevents package-hardcoding and guarantees uniform entrypoint and bundle
enforcement across all current and future ported packages.

**Rejected alternatives.** Enumerating package test paths in CI (reintroduces
silent-miss risk on subsequent ports); creating a root `conftest.py` (couples the
catalog root to package-specific fixtures); editing `plugins/mission-control/CHANGELOG.md`
to force a floor declaration (breaks byte-copy provenance digest).

**Revisit when.** A future port requires multi-package integration fixtures or
modifies interpreter floor requirements.

**Refs.** Child #16, [run plan U6](../plans/2026-08-24-mission-control-port-run-plan.md),
[two-CI-job decision 2026-08-22](#two-continuous-integration-jobs-hermetic-validation-and-floor-pinned-plugin-tests),
[ported tests inside package decision](#ported-tests-live-inside-the-package-under-the-provenance-closed-set-check),
[descriptor closed decision](#the-port-descriptor-is-closed-and-its-safety-fields-are-stated-rather-than-defaulted),
[portable README runnable surface decision](#the-portable-mission-control-readmes-runnable-surface-is-usage-probes-and-its-links-bind-only-what-lane-b-lands-u4),
[cycle-15 mutation proof survivor disclosure](../../docs/evidence/2026-08-24-cycle15-mutation-proof-portable-copies.txt).

---

### The portable mission-control README's runnable surface is usage probes, and its links bind only what Lane B lands (U4)

**Author.** Jeff Cox and Qwen (orchestrated unit U4, issue #14)

**Decision.** Two shapes of the target-owned package README
(`plugins/mission-control/README.md`). First: the only commands it documents
in runnable `bash` fences are repository checks and `--help` usage probes of
the five package entrypoints. Every live mission-control subcommand reaches
GitHub through the `gh` CLI, so any fenced live command would force the
README's enforcement test (`tests/test_mission_control_readme.py`) to make a
live GitHub call with ambient credentials or to fail — the first violates the
run plan's no-live-GitHub rule (R5), and the second is the exact
"documented command that cannot run" defect the test exists to catch. Usage
probes prove import and argument parsing, not live behavior; live behavior
needs an authenticated `gh`, and the read-only versus GitHub-mutating split
is therefore documented as an audited table, not as runnable fences. Second:
relative links bind only paths present when Lane B lands (the target-owned
manifest, the descriptor, the repository tooling); paths the parallel sync
and bundle lanes land later (`scripts/`, `skills/`, `config/`,
`com.infiquetra.claude/`, `PROVENANCE.json`, `fleet-bundle.json`,
`scripts/_bundled/`) are referenced as literals. `check_markdown_links` and
`test_check_repo.py`'s live-tree assertion run per branch, so a link to a
file another lane has not landed yet is a broken link on this branch and in
every integration state before that lane merges. The enforcement test skips
its Lane A/C-guarded assertions (command runnability with `GH_`/`GITHUB_`
variables stripped, PROVENANCE target-owned custody) with a reason when the
artifacts are absent and asserts them fully when present; the assembled
integration branch is where everything is required green.

**Rejected alternatives.** Fencing live commands and extending the test's
skip list to them — that removes runnability enforcement from exactly the
commands most likely to rot, restoring the pilot's defect in a new shape.
Relative links to synchronized paths — broken on this branch and on the
integration branch until each owning lane lands, turning another unit's merge
order into this README's gate failures. Byte-copying the upstream README —
the codified pilot failure: it introduces the Claude Code plugin, hardcodes a
stale installed script path under the plugin cache, and omits `flow` from its
own skills table, and a later resync would restore all three.

**Rationale.** The UniFi README can fence live operations because UniFi's
discovery and drift commands are credential-free and offline; mission-control
has no such surface, so its runnable verification contract is the usage probe
— the same shape `tests/test_client_entrypoints.py` uses. Keeping links green
at every branch state matches the run plan's landing model, under which
intermediate states may fail only named package-completeness checks.

**Revisit when.** Mission-control grows a genuinely credential-free,
network-free read mode (the way UniFi has discovery and drift); it then joins
the fenced surface under this same test.

**Refs.** Child #14, [run plan U4](../plans/2026-08-24-mission-control-port-run-plan.md),
[`tests/test_mission_control_readme.py`](../../tests/test_mission_control_readme.py),
[`tests/test_unifi_readme.py`](../../tests/test_unifi_readme.py)
### Schema 3 moved a graded file: the cycle-14 mutation proof is re-run with U8's evidence, not here

**Author.** Jeff Cox and Qwen (orchestrated unit U3, issue #13)

**Decision.** U3's schema-version-3 change to `scripts/port_config.py` moves
the bytes of one of the five files `MutationProofBindingTest` grades, so the
cycle-14 portable-copies mutation proof
(`docs/evidence/2026-08-24-cycle14-mutation-proof-portable-copies.txt`) binds
a superseded digest and the binding test fails on every branch carrying this
change. The proof is re-run and republished with U8's Phase-3 evidence
collection — evidence bound to the frozen assembled state — not inside this
unit. Until then the intermediate branch state carries exactly one failure
beyond the named Lane B/C package-completeness checks (the missing portable
manifest, resolved by U4): the proof-binding test.

**Rationale.** The binding test exists to fail in exactly this situation — a
graded file edited without its proof re-run — so the failure is the mechanism
working, not a defect in this unit. Editing the recorded digests without
re-running the proof would be the evidence tampering the cycle-7 lesson built
the test to prevent. The run plan gives the re-run a named home: U8's evidence
set ("one mutation proof per rule copy with binding tests") is re-collected
against the frozen branch, at which point the proof rebinds every graded
file's final bytes.

**Rejected alternatives.** Re-running the proof inside U3 (a full mutation-
proof cycle is outside a synchronization unit's scope, and the tooling bytes
are not final until the lanes land); editing the digest lines (tampering);
amending the binding test to tolerate interim states (weakens the guarantee
for every future graded-file edit).

**Revisit when.** U8's Phase-3 evidence re-runs the portable-copies proof
against the frozen assembled branch; this entry is superseded by that proof's
publication.

**Refs.** `tests/test_site_profile.py` (`MutationProofBindingTest`),
`docs/evidence/2026-08-24-cycle14-mutation-proof-portable-copies.txt`,
[run plan U8 evidence set and landing model](../plans/2026-08-24-mission-control-port-run-plan.md),
child issue #13.

---

### Transform-rule selection is an explicit per-path rule field, validated by two modules

**Author.** Jeff Cox and Qwen (orchestrated unit U3, issue #13)

**Decision.** Descriptor schema version 3 reinterprets
`custody.entrypoint_transforms`: every entry is an object carrying `path` and
`rule`, both required and the object closed; a bare path string (the schema-2
shape) or an entry with no rule name is refused rather than read with an
assumed default rule. The rule name is validated by two modules:
`scripts/port_config.py` validates the entry's shape (the descriptor format's
sole authority), and `scripts/sync_vendor_source.py` validates at plan time
that the name exists in its `TRANSFORM_RULES` registry. Three rules join the
existing two: `resolve-bundled-fleet-module-split` v1 (a module-scope import
block whose load call sits elsewhere in the file),
`resolve-bundled-fleet-module-guarded` v1 (a function-scope, if-guarded
contiguous block that returns the loaded module), and
`normalize-skill-frontmatter` v1 (folds a top-level `when_to_use` under the
permitted `metadata` key, line-based because the tooling is standard-library
only). Both committed descriptors migrated in the same commit as the version
bump; `resolve-bundled-fleet-module` v1 and its committed UniFi provenance
stay byte-untouched.

**Rationale.** `port_config` cannot know the sync registry without inverting
the import direction (the sync tool imports `port_config`, never the reverse),
so existence lives with the registry's owner and shape with the format's
owner; a typo'd rule name fails at the next synchronization, and
`tests/test_port_config.py` joins the two so it fails at the gate instead. The
split rule pays the import at module scope where upstream paid it at call time
— the lint script always needs the palette when it lints; the guarded rule
keeps upstream's lazy call-time import and moves only the existing binding's
value, keeping the binding name a deterministic rule cannot know is unused
beyond the block. The fold lands where the key stood and refuses a frontmatter
carrying a top-level `metadata` key beside `when_to_use` — folding under an
existing mapping is a shape version 1 does not describe — and a frontmatter
without the key comes back unchanged, which is the idempotence guarantee. The
Python API keeps `entrypoint_transforms` a tuple of path strings with
`entrypoint_rules` beside it, so consumers this unit does not own keep
iterating paths unchanged.

**Rejected alternatives.** A default rule for entries with no rule name
(selection becomes a default — the failure the version bump exists to refuse);
a rule-name registry inside `port_config.py` (couples the format authority to
one tool's rule set and inverts the import direction; also the script-internal
registry AGENTS.md's custody rule names); merging the fold into an existing
`metadata` mapping (an undescribed shape); renaming the guarded block's
directory binding (a byte change beyond the block the rule can see).

**Revisit when.** A third shim shape appears at a future pin (the family grows
a named rule; an existing rule is never loosened to match it); the open Agent
Skills specification adopts `when_to_use` (the fold retires); a future port's
frontmatter carries `when_to_use` beside an existing `metadata` key (the fold
learns the merge shape and bumps its version).

**Refs.** [run plan KTD1/KTD2/KTD3](../plans/2026-08-24-mission-control-port-run-plan.md),
child issue #13, `scripts/sync_vendor_source.py` (`TRANSFORM_RULES`,
`resolve_transform_rule`), `scripts/port_config.py`
(`_entrypoint_transform_entries`), `ports/README.md`.

---

### Mission-control fleet-commons closure: three files, with intent_envelope as a recorded deterministic transform (KTD8)

**Author.** Jeff Cox and Claude (execution coordinator for issue #9)

**Decision.** The fleet-core slice U2 ports for mission-control is three files,
not two: `intent_envelope.py`, `tier_palette.py`, and the `models.json`
registry, all at the existing pin `3b5faa6c`. `tier_palette.py` and
`models.json` stay pure byte copies; `intent_envelope.py` ports under
fleet-core's existing `deterministic-transform` custody class with a new named
rule `resolve-fleet-commons-sibling` v1 that replaces its module-scope
`fleet_commons_shim` import block and its two `fleet_commons_shim.load()` call
sites with same-directory sibling resolution, recorded as a package `files`
entry with classification `deterministic-transform` (source digest, transform
version, result digest — the package-resident shape `check_repo.py`
validates; corrected per the amendment doc review, F2). The upstream
`tests/test_intent_envelope.py` is not ported (it imports the saga re-export
at module level, loads team-execution, mission-control, and shim surfaces
during test execution, and exercises saga-only APIs; wording per F4); U2
authors minimal target-owned tests instead. `tier_resolver.py` and `tier_policy.json` stay
deferred: at mission-control pin `84eaf042`, `recommend_tier` /
`self_select_posture` / `authorize_spend` have zero callers in either consumer
(`sdlc_manager.py`, `executor_profile_lint.py`), while
`SpendEnvelope.validate()` makes `tier_palette` + `models.json` reachable on
the shipped envelope-parse path. Full evidence and the rejected alternatives
are KTD8 in the
[run plan](../plans/2026-08-24-mission-control-port-run-plan.md); the trigger
was the first U2 dispatch stopping on child #12's own stop condition item 1
(evidence `.orchestrate-unit-blocked.md`, commit `68cf5fc` on
`orch/mcport-9-resume1-u2-fleetcore-q1`).

**Rejected alternatives.** Porting the full tier closure (zero callers —
speculative); a target-owned `fleet_commons_shim.py` adapter under the
upstream name (a second implementation under an upstream-custody name — the
divergent-source failure the custody model exists to prevent); byte-copying
`intent_envelope.py` unchanged (cannot import anywhere in the target);
repinning fleet-core (the closure is byte-identical at both pins; a repin
buys nothing and regenerates UniFi's bundles).

**Rationale.** Same-directory sibling resolution is placement-independent, so
one transformed file works both in `plugins/fleet-core/scripts/fleet_commons/`
and in mission-control's `scripts/_bundled/`, keeping KTD1's entrypoint rules
and the shim drop-from-source unchanged; the `deterministic-transform` class
already exists in fleet-core custody (`guard-pytest-import` v2), so no new
custody machinery is invented.

**Revisit when.** Mission-control's upstream consumption starts calling a
`tier_resolver`-backed API — the dormant leg then joins the slice by this same
mechanism.
### A skill key the open specification does not permit is transform custody, upstream keeps it

**Author.** Jeff Cox and Qwen (orchestrated unit U1, issue #11)

**Decision.** All seven upstream mission-control `SKILL.md` files carry a
`when_to_use:` frontmatter key that is not among the six fields
`SKILL_FRONTMATTER_FIELDS` permits (`scripts/check_repo.py`), and the UniFi
precedent never met one. The port descriptor
([ports/mission-control.json](../../ports/mission-control.json)) classifies
the seven files in `entrypoint_transforms` — the descriptor's only transform
custody — so a versioned `normalize-skill-frontmatter` rule can fold the key
under the permitted `metadata` key at synchronization, deterministically and
idempotently, portable copies only. Upstream keeps the key.

**Rationale.** A byte copy of any of the seven files would fail
`check_skill_frontmatter` on the assembled branch — the exact failure class
the gate exists to catch — so the custody must name a transform. Upstream
normalization is rejected because `when_to_use` is functional in Claude Code
skill listings; folding the key into the document body is rejected as a lossy
placement that is harder to check for idempotence. Per-path rule selection is
the schema-3 field the synchronization unit owns (run plan KTD2/KTD7), so this
unit records the custody class and not the rule name.

**Rejected alternatives.** Normalizing upstream (functional key in Claude
Code listings — the contract's recorded rejection); byte copy plus gate
exemption (a hole in the frontmatter rule for one package); body fold (lossy
placement, harder idempotence check).

**Revisit when** a third package carries a frontmatter key the open Agent
Skills specification does not permit, or the specification adopts
`when_to_use` and the fold becomes unnecessary.

**Refs.** [U1 Phase 0 note](../plans/2026-08-24-mission-control-port-u1-phase0-note.md),
[run plan KTD3/KTD7](../plans/2026-08-24-mission-control-port-run-plan.md),
`ports/mission-control.json` (`custody.entrypoint_transforms`), child issue #11.

---

### Ported tests live inside the package, under the provenance closed-set check

**Author.** Jeff Cox and Qwen (orchestrated unit U1, issue #11)

**Decision.** The twenty-one carried upstream mission-control test files are
byte copies under `plugins/mission-control/tests/` — inside the package tree,
therefore inside the provenance closed-set check — rather than at the
repository root.

**Rationale.** The pilot's one-off precedent carried its tests at the
repository root, tracked by fleet-core's informal `release_surface` key that
no check validates; a repeat of that shape would ship tests the provenance
machinery cannot see and the fingerprint cannot bind. Placement inside the
package keeps every test in the closed set `check_repo.py` and the
provenance manifest account for, and it is what lets the U6 CI wiring run
them through the `plugins/*/tests` glob.

**Rejected alternatives.** Repo-root tests tracked by the unvalidated
`release_surface` key (the pilot's precedent — invisible to every check this
repository has); a descriptor key declaring external tests (a second home for
a fact the provenance manifest should own).

**Revisit when** a ported package's tests genuinely cannot live under its
package root — for example, a test suite that must observe more than one
package at once — and the closed-set check would need a declared exception.

**Refs.** [U1 Phase 0 note](../plans/2026-08-24-mission-control-port-u1-phase0-note.md),
`ports/mission-control.json` (`custody.byte_copies`), run plan U1 rejected
alternative, child issue #11.

---

### A whole-repository drift guard is dropped when its premises cannot cross the port boundary

**Author.** Jeff Cox and Qwen (orchestrated unit U1, issue #11)

**Decision.** `tests/test_prompt_alignment.py` is classified
`dropped_from_source` in
[ports/mission-control.json](../../ports/mission-control.json), with the
custody finalized in U1 before synchronization (run plan doc-review F2). The
premise verification at the pin found six structural failures under the
portable layout: the test reads the Claude manifest at the package-local
`.claude-plugin/` path (relocated to `com.infiquetra.claude/`), the root
`.claude-plugin/marketplace.json` and the `plugins/saga` handoff skill
(neither exists in this catalog — both probed absent), the commands and agent
file at their unrelocated upstream paths, and the package README (superseded
by the target-owned one). Only its package-internal byte-copy premises hold.

**Rationale.** The guard is a whole-upstream-repository drift guard, not a
package-scoped one: its authority is the upstream repository layout itself. A
byte copy would ship a test that errors at collection in the portable package
suite; editing its content to make it pass is the custody violation the run
plan's U6 names ("a test that cannot pass without content change is an
upstream filing or a recorded custody decision"). This is the recorded
custody decision. The guard stays green upstream, where its premises hold,
and nothing about this drop weakens the portable tree: the content it guards
still travels as byte copies whose digests the provenance manifest pins.

**Rejected alternatives.** Byte copy (errors at collection in the U6 package
suite); content edit to satisfy the portable layout (custody violation);
target-owned replacement test asserting the same phrases (invents a new
moving part no unit owns, over a premise set the portable catalog cannot
honor); carrying it and skipping at runtime (a permanently-skipping test is
deadweight that misrepresents its own coverage).

**Revisit when** this catalog grows a marketplace manifest or hosts the saga
plugin, so the guard's repository-level premises can exist here; then the
test returns through a deliberate repin + resync, never a downstream patch.

**Refs.** [U1 Phase 0 note](../plans/2026-08-24-mission-control-port-u1-phase0-note.md)
(premise-by-premise verdict table), `ports/mission-control.json`
(`custody.dropped_from_source`, `provenance.dropped_reason`), run plan
open-questions section (F2 disposition), child issue #11.

---

### Mission-control port run plan: new transform rules stay single-shape, rule selection lives in the descriptor

**Author.** Jeff Cox and Claude (Saga Plan for issue #9)

**Decision.** The mission-control port run plan
([docs/plans/2026-08-24-mission-control-port-run-plan.md](../plans/2026-08-24-mission-control-port-run-plan.md))
fixes five plan-level choices inside the operator-approved contract of issue
#9: (1) the two mission-control entrypoint consumers get two **new** named
single-shape transform rules, each preserving exactly-one-match discipline, and
the existing `resolve-bundled-fleet-module` v1 stays byte-untouched; (2)
transform-rule selection becomes an explicit per-path field in the port
descriptor at a new schema version 3 (the format authority mandates a bump
when a field is added, `port_config.py:54`; corrected in the S3 disposition
pass per doc-review F1), with both descriptors migrated and
`ports/unifi.json` naming its rule explicitly in the same commit; (3) the `when_to_use:` skill-frontmatter key is
folded under the permitted `metadata` key by a new `normalize-skill-frontmatter`
v1 transform, portable copies only; (4) CI package-test wiring uses the
`plugins/*/tests` glob — the empty-collection case closed in the job's own
command shape, a separate path-agreement check only if a concrete collection
failure remains (doc-review F6) — rather than per-package enumeration; (5) the card-validator verdict-agreement test derives
its authority live from the home-lab checkout and self-skips loudly when the
checkout is absent.

**Rationale.** Bumping the existing rule to a multi-shape v2 would loosen the
exactly-one-match discipline and change the transform identity UniFi's
committed provenance records; AGENTS.md places porting-tool package
configuration in the descriptor, never in a script constant; `metadata` is one
of the six fields `check_repo.py` permits, so the fold is deterministic,
idempotent, and lossless; the glob plus corrected empty-collection handling means the next port cannot
silently ship uncollected tests; a copied-constant authority corpus cannot fail
when the authority moves.

**Rejected alternatives.** *One loosened multi-shape rule v2* and *first-match
semantics* (a #13 stop condition). *A script-internal path-to-rule registry*
(the custody violation AGENTS.md names). *Keeping `schema_version` `"2"` for the rule-name field* — corrected in the
S3 disposition pass: `port_config.py:54` mandates a bump when a field is
added, so U3 takes version 3 (doc-review F1). *Folding `when_to_use` into the skill body* (lossy placement, harder
idempotence) and *normalizing upstream* (the key is functional in Claude Code
listings). *Vendoring a second card-validator authority copy here* (a third
copy that can disagree).

**Revisit when** a third port needs a transform shape neither new rule covers
(that is the moment to consider a general rule grammar, not before), or when
fleet-core migrates onto a port descriptor and the descriptor-vs-PROVENANCE
custody split changes.

### A deadline-killed command is marked timed out, not given a fake exit status

**Author.** Jeff Cox and Grok

**Decision.** A command the harness kills at the stage deadline is recorded with
`timed_out: true` and no `exit_status`. A command that exited or was terminated by a
signal carries `exit_status` (the process wait status) and no `timed_out`. The two
fields are mutually exclusive. subprocess returncode is `-N` for termination by
signal N, so `-1` is SIGHUP and is recorded as `exit_status: -1`. The schema lists
both fields; `check_compatibility_matrix.py` refuses a command entry that has both,
neither, or `timed_out` set to anything other than true. Existing committed records
carry `exit_status` only and still validate.

This supersedes [A command that hit the deadline is recorded like any other
command](#a-command-that-hit-the-deadline-is-recorded-like-any-other-command),
which reserved `-1` for the deadline and claimed no real exit status can say that.
The "it ran, so it is in `commands` and is safety-graded" half of that decision
stands.

**Rationale.** A sentinel that collides with a real wait status is not a sentinel.
The previous form made "killed at the deadline" and "terminated by SIGHUP"
indistinguishable in every consumer of the public record and of the private
transcript. Omitting `exit_status` is no longer "not recorded": `timed_out: true`
is the positive marker that the command did not exit.

**Rejected alternatives.** *Keep `exit_status: -1` and add `timed_out` beside it*,
because then `-1` is still a lie about the wait status, and a reader who only
looks at `exit_status` still cannot tell SIGHUP from a deadline. *Record the
wait status after SIGKILL (`-9`) plus `timed_out`*, because that status describes
the harness's kill, not the client, and a failed wait still has no integer to
put there. *Use a non-integer `exit_status` (`null` or `"timed-out"`)*, because
the schema subset this repository interprets has no union types, and a string
status would invalidate the "integer wait status" reading of every existing
entry. *Bump to schema version 3*, because the new field is additive and every
committed record still validates as version 2.

**Consequence to expect.** A blocked stage's last `commands` entry is often
`{"command": "...", "timed_out": true}` with no `exit_status`. Operators filling
the public record from the private transcript will see the same shape there;
copying `-1` into a matrix as a deadline marker is now a validator failure only
when `timed_out` is also present, and is SIGHUP when it is not.

**Revisit when.** A command needs to record both that the deadline fired and the
wait status the kill actually produced.

**Refs.** `schemas/compatibility-matrix.schema.json`,
`scripts/assess_clients.py` (`StageCommand`, `CommandTranscript`),
`scripts/check_compatibility_matrix.py` (`_command_ending_problems`),
`tests/test_assess_clients.py` (`test_a_command_terminated_by_sighup_is_not_recorded_as_a_deadline`),
`tests/test_check_compatibility_matrix.py` (`PerCommandStatusRecordTest`).

### A supplied run directory is still a fresh run directory

**Author.** Jeff Cox and Grok

**Decision.** `assess` still takes an optional `run_directory` so the write path and
the announced path are one value. A supplied path must exist as a directory, must
be empty, and when a workspace is also given must be a subdirectory of it, not
the workspace itself. The caller still allocates; this check is the invariant
`allocate_run_directory` already established, applied to the parameter that used
to skip it.

**Rationale.** The parameter was added so two call sites would not derive one path.
Accepting any truthy path meant a caller could hand `assess` a directory that
already held a previous run's package copies and transcript, mix two assessments,
and overwrite the first transcript through `write_private`. That is the
one-run-one-directory evidence boundary, routed around.

**Rejected alternatives.** *Refuse a supplied path that already exists*, because
`allocate_run_directory` creates the directory before passing it in, so existence
is the happy path; emptiness is the freshness test. *Delete the parameter and
return the path from `assess`*, which is the alternative the previous decision
rejected, and which would churn every caller to fix a missing check. *Trust
`copytree` to fail if a per-client copy already exists*, because a second run
that assessed a different client would not collide on that copy and would still
overwrite the transcript.

**Consequence to expect.** Tests that pass `run_directory` must create an empty
directory first, matching `main`. A reused `--workspace` still accumulates
`run-NNN` directories; only a caller that names a dirty one is refused.

**Revisit when.** More than one artifact has to be announced, at which point a
small run-context object still beats a widening parameter list.

**Refs.** `scripts/assess_clients.py` (`require_fresh_run_directory`, `assess`),
`tests/test_assess_clients.py` (`WorkspaceFreshnessTest`),
[the caller-allocates decision](#the-caller-that-has-to-name-the-run-directory-is-the-caller-that-allocates-it),
[the one-run-one-directory decision](#every-assessment-run-gets-its-own-directory-and-every-client-its-own-package-copy).

### A slice expansion at an unchanged pin releases without moving the tracked version

**Author.** Jeff Cox and Qwen (orchestrated unit U2, issue #12)

**Decision.** The 2026-08-24 fleet-core slice expansion ([KTD8](#mission-control-fleet-commons-closure-three-files-with-intent_envelope-as-a-recorded-deterministic-transform-ktd8))
records its changelog entry under Unreleased and keeps
`plugins/fleet-core/plugin.json` at `0.25.2`. Child #12 directed a "version
bump per the package release convention," but the convention's own terms
forbid moving the number here: the version tracks the upstream Fleet Core
version the package's bytes derive from, and upstream released 0.25.3 on
2026-08-24 changing `retry_backoff.py` — which this pin deliberately does not
take, because a repin churns UniFi's bundles and invalidates its committed
matrix. Naming this package 0.25.3 while it still carries 0.25.2's
`retry_backoff` bytes would collide with the real upstream release; inventing
any other number is the parallel numbering the changelog preamble rejects.

**Rationale.** A version string in this catalog is a derivation claim, not a
release counter: readers and the bundle stamps resolve it against
`PROVENANCE.json`'s pin, and the two must not disagree. The expansion moves no
byte already here, so the Unreleased precedent the python-floor entry set
applies; the changelog entry itself records the no-bump reasoning.

**Rejected alternatives.** Bumping to 0.25.3 (false derivation and a collision
with the actual upstream release); a package-local suffix such as
`0.25.2-slice.1` (an invented parallel numbering the convention exists to
prevent); repinning to take upstream 0.25.3 (a #12 stop condition).

**Revisit when.** Fleet-core repins — the version moves with the pin, and the
Unreleased entries release under it.

### The U2 empty-shim-grep probe binds the transformed module, not the whole package

**Author.** Jeff Cox and Qwen (orchestrated unit U2, issue #12)

**Decision.** Child #12's acceptance probe `git grep fleet_commons_shim
plugins/fleet-core/` (expected empty) is enforced in intent, not literally.
The transformed `intent_envelope.py` carries zero references to the
discovery shim and nothing in the slice imports or needs it, but the literal
already lived in the committed package before this unit and must keep living
there: the byte-copied `retry_backoff.py` docstring names the shim, and
byte copies cannot be edited without breaking their recorded digests; the
generated deferred inventory names `fleet_commons_shim.py` as a deferred
item, a row the same card requires to stay ("every other deferral stays
explicit") and the suite pins. The contract's empty-grep verification is the
one KTD1 gives U3, scoped to `plugins/mission-control/scripts/`.

**Rationale.** An acceptance probe that contradicts two other acceptance
items in the same card (byte-copy digest equality and explicit deferrals)
cannot be the literal contract. The property all three items share — and the
one the first U2 dispatch's failure made concrete — is that no ported module
depends on the shim at import or call time.

**Revisit when.** Never for fleet-core while it carries byte copies whose
upstream prose names the shim; the mission-control probe in U3 is the one
that must end empty.

## 2026-08-23

### A command that hit the deadline is recorded like any other command

**Author.** Jeff Cox and Claude

**Superseded 2026-08-24.** The command still goes in `commands` and is still
safety-graded. The representation is no longer `exit_status: -1`: that value is
SIGHUP. See [A deadline-killed command is marked timed out, not given a fake exit
status](#a-deadline-killed-command-is-marked-timed-out-not-given-a-fake-exit-status).

**Decision.** When a stage's command reaches its deadline, that command is appended to the
stage's `commands` list with `exit_status: -1`, alongside its entry in the private transcript.
It is therefore in the public version-2 record and is graded by the post-run safety rule like
every other recorded command. `-1` is reserved for "killed at the deadline, never exited"; no
real exit status can say that.

**Rationale.** The stage started it, so it ran. Keeping it only in the private transcript left
the public record naming fewer commands than the stage started — unreproducible — and left the
safety rule, which grades `commands`, blind to the single command most likely to have been doing
something unbounded. A record that omits the command that hung is a record that reads best
exactly when the run went worst.

**Rejected alternatives.** *Omitting `exit_status` for that entry*, because the schema requires
an integer and an absent field would read as "not recorded" rather than "did not exit".
*Recording it only when the stage is blocked for some other reason*, because the deadline is the
common case. *Grading safety only on `executed` stages*, because a blocked stage's commands
started.

**Consequence to expect.** A blocked stage can carry more `commands` entries than it has
`returncodes`; the per-command statuses are the reproducible record and the returncodes are what
classified the stage.

**Revisit when.** The schema gains a way to mark a command as terminated rather than exited.

**Refs.** `scripts/assess_clients.py`, `schemas/compatibility-matrix.schema.json`,
`tests/test_check_compatibility_matrix.py` (`PerCommandStatusRecordTest`).

### The caller that has to name the run directory is the caller that allocates it

**Author.** Jeff Cox and Claude

**Decision.** `assess` takes an optional `run_directory`. The command line allocates it and
passes it in, so the path the transcript is written to and the path the closing message
announces are the same value rather than two computations that agree by convention. `assess`
still allocates one itself when no caller supplies it, which is what every test relies on.

**Rationale.** The run-directory repair moved the transcript into `<workspace>/run-NNN/` and the
message went on naming `<workspace>/`, so every executed assessment sent the operator to a file
that did not exist — and the transcript is the only place the record's blank versions, reasons,
and evidence can be filled from. Two call sites deriving one path is the arrangement that
allowed them to disagree; passing the value removes the second derivation rather than fixing it.

**Rejected alternatives.** *Putting the run directory in the record*, because the record is
public evidence and a local filesystem path does not belong in it. *Returning a tuple from
`assess`*, because every caller and test would change to carry a value only one of them wants.
*Recomputing the newest `run-NNN` in the command line*, because it re-derives what was already
decided and is wrong the moment two runs share a workspace.

**Consequence to expect.** A caller that needs the path must allocate before assessing, which is
one line and makes the ordering explicit.

**Extended 2026-08-24.** Naming the directory does not exempt it from being a fresh one.
See [A supplied run directory is still a fresh run directory](#a-supplied-run-directory-is-still-a-fresh-run-directory).

**Revisit when.** More than one artifact has to be announced, at which point a small run-context
object beats a widening parameter list.

**Refs.** `scripts/assess_clients.py` (`assess`, `main`), `tests/test_assess_clients.py`
(`CommandLineTest`),
[the producer-and-consumer learning](LEARNINGS.md#both-regressions-updated-the-producer-and-left-the-consumer-behind).

### A mutation proof excludes its own binding test, and is never corrected by hand

**Author.** Jeff Cox and Claude

**Decision.** The mutation runner excludes `MutationProofBindingTest` from grading entirely —
at baseline and under every mutation — and counts a mutation killed only when it fails some
other test that was passing at baseline. It records the baseline failure set first and aborts
if anything outside that binding test is failing. The published proof states the exclusion in
its header. When an anchor no longer matches exactly once, the run aborts, the files are
restored, the anchor is rewritten to name the guard in its current form, and the whole set is
re-run; a pre-flight pass checks every anchor before the expensive run begins.

**Rationale.** Every mutation edits a graded file, which changes its digest, which fails the
binding test. Counting that as a kill made every mutation a kill by construction, and cycle
11's "0 survivors" was measuring the runner's own bookkeeping. Re-graded with the exclusion,
seven anchors had no test behind them. Separately, the binding test cannot pass until the run
it describes is published, so demanding a green baseline created exactly one route to one —
editing the previous cycle's recorded digests, which is the cycle-7 defect that test exists to
catch.

**Rejected alternatives.** *Excluding the binding test from the suite the runner invokes*,
because the exclusion then stops being visible in the published proof. *Writing the expected
digests into the evidence file before the run*, because a proof whose digest block was authored
rather than computed identifies nothing. *Publishing a partial pass and appending the remaining
mutations afterwards*, because the digests would name a tree no single run exercised.
*Excluding only the binding subtests that fail at baseline*, because that still lets the test
kill a mutation to any graded file whose digest currently matches — which is every graded file
the round did not change.

**Consequence to expect.** Every code change to a graded file costs a full re-run of the proof,
roughly forty minutes, before the suite can be green again. A survivor count above zero is now
a real finding rather than a broken run.

**Revisit when.** The suite grows a second test that cannot pass until the artifact it checks
is published, or the graded set grows enough that the run stops fitting in one sitting.

**Refs.** `tests/test_site_profile.py` (`MutationProofBindingTest`),
`docs/evidence/2026-08-23-cycle12-mutation-proof-portable-copies.txt`,
[the vacuous-proof learning](LEARNINGS.md#the-mutation-proof-counted-its-own-bookkeeping-as-a-kill).

### A client's real executable is supplied by the operator, never discovered

**Author.** Jeff Cox and Claude

**Decision.** Two of the ten clients launch through a local auto-trust wrapper that finds its
real binary through the client home, and that lookup fails under the isolated home the harness
gives it. `resolve_real_binary` takes the real path from `--real-binary NAME=PATH` for the run,
or from the wrapper's own documented override already exported in the operator's environment.
With neither, the client is `blocked` with the requirement named. The harness never searches
`PATH` for it, and refuses a supplied path that is the same file as the launcher on `PATH`.

**Rationale.** Nothing on disk distinguishes a launcher from the thing it launches. The first
version resolved the value with `which`, which returns the wrapper — the wrapper is what sits on
`PATH` under that name — so the wrapper exec'd itself and spawned descendants until the host ran
out. The repair took the first `PATH` entry that was not the *same file* as the wrapper, which a
second *copy* of the wrapper satisfies: the same defect one arrangement further out. Both
attempts guess which of several same-named executables is "the real one", and that guess cannot
be made correct — only made to look correct on the machine it was tried on.

**Rejected alternatives.** *Comparing file size or reading the first line*, because a wrapper
that grows or loses its shebang defeats it and nothing announces that it has. *Skipping the two
clients*, because their support status is exactly what the assessment exists to establish.
*Guessing and capping the recursion depth*, because a bounded process bomb is still a process
bomb and the record it produces describes the cap, not the client.

**Consequence to expect.** An operator who has never exported the override sees two clients
`blocked` naming the variable, not two clients silently assessed against a wrapper.

**Revisit when.** A wrapper ships a documented, machine-readable way to name its real target.

**Refs.** `scripts/assess_clients.py` (`resolve_real_binary`), `tests/test_assess_clients.py`
(`RealBinaryResolutionTest`),
[the wrapper learning](LEARNINGS.md#a-wrapper-resolved-by-name-resolves-to-itself).

### Every assessment run gets its own directory, and every client its own package copy

**Author.** Jeff Cox and Claude

**Decision.** `--workspace` names a place runs live in, not a place a run owns.
`allocate_run_directory` claims `run-001`, `run-002`, … inside it with `exist_ok=False`, and
each client's package copy is made unconditionally into that new directory. Copying is never
skipped because the destination already exists.

**Rationale.** The record binds itself to the shipped package fingerprint. An operator pointing
`--workspace` at the same place on every run is the normal case, and a conditional copy handed
the next run whatever the last one left — including a copy a client had installed into. That
tree then assessed as if it were the shipped package while the record went on naming the shipped
digest, which is a record that identifies the wrong bytes. Numbered rather than random so a
returning operator can tell which run is which.

Two guards cover one defect here, deliberately. The fresh directory makes the collision
impossible and the unconditional copy refuses it if it happens anyway; the second is what
survives someone changing the first.

**Rejected alternatives.** *Reusing a copy that still matches the fingerprint*, because it makes
the guarantee depend on a check that the reuse exists to skip. *Deleting the workspace at
start*, because it destroys the previous run's transcript, which is the only place raw client
output is kept. *A temporary directory per run*, because the operator cannot find it afterwards
and the transcript has to be found.

**Consequence to expect.** Repeated runs accumulate `run-NNN` directories the operator prunes
deliberately; disk is spent to keep every run's evidence separable.

**Revisit when.** The workspace layout has to be shared with another tool that expects a fixed
path.

**Refs.** `scripts/assess_clients.py` (`allocate_run_directory`),
`tests/test_assess_clients.py` (`WorkspaceFreshnessTest`).

### The port descriptor is closed, and its safety fields are stated rather than defaulted

**Author.** Jeff Cox and Claude

**Decision.** Every object in a port descriptor refuses keys the contract does not define, and the
four `assessment` fields that carry a safety decision — `credential_prefixes`, `package_scripts`,
`mutating_operations`, `entrypoints` — must each be stated. A package for which one is genuinely
empty writes it as an empty list *and* names it in `assessment.declared_none`. The descriptor version
advanced to `2`; version 1 is not accepted, because a descriptor written against it has exactly the
shape this closes.

`assessment.entrypoints` is also new, and is deliberately independent of the `custody` table: what
makes a file executable is that the package says it is, not how its bytes were obtained.

**Rationale.** Each of those four fields fails *open* when empty, and "absent" and "empty" were the
same state. `credential_prefix` for `credential_prefixes` validated, loaded, passed the repository
gate, and stripped nothing — the cheapest possible mistake buying the most expensive possible
outcome. Reading entrypoints out of `custody.entrypoint_transforms` had the narrower version of the
same problem: a package whose executable is an upstream byte copy had no assessable entrypoint, so
the "package-agnostic" harness only ever worked for one custody layout.

**Rejected alternatives.** *Warning on an unknown key*, because a warning in a tool nobody watches is
a comment. *Defaulting the safety fields and documenting that they matter*, because documentation is
not a gate and the failure is silent. *Inferring an empty field as deliberate*, because that is
indistinguishable from a typo, which is the whole defect. *Accepting version 1 leniently for
migration*, because the un-migrated package is precisely the one still carrying the hole.

**Consequence to expect.** Adding a package is more verbose: four safety fields must be written even
when three are empty. That verbosity is the point — the empty case is now something a person decided
and a reader can see.

**Revisit when.** A safety field is added or retired, or a package needs a per-field exemption the
`declared_none` list cannot express.

**Refs.** `scripts/port_config.py`, `ports/README.md`, `tests/test_port_config.py`,
[the learning](LEARNINGS.md#an-optional-safety-setting-is-a-safety-setting-that-is-off).

### A compatibility record stores every command a stage ran, beside its own exit status

**Author.** Jeff Cox and Claude

**Decision.** The compatibility-matrix record advances to `schema_version` 2. An executed stage
carries `commands`: every argv it ran, redacted, each with its own `exit_status`. `command` remains
the first of those, so a row still reads as version 1 did. Version 1 records stay valid and keep
being validated; a version 1 record carrying `commands` is refused, and a version 2 executed stage
without them is refused.

**Rationale.** A stage runs one command per skill unit, or one per entrypoint. Recording only the
first made the command and status cardinalities disagree: a reader saw `exit status 0, 7` with one
command and could neither tell which failed nor reproduce it. The nine committed matrices are
evidence and are not rewritten, so the version is what separates the two shapes rather than a
migration.

**Rejected alternatives.** *Keeping one command and listing statuses in prose*, which is the
disagreement itself. *Rewriting the committed matrices to the new shape*, because editing evidence to
match a moved tree is the anti-pattern the runbook names. *Making `commands` optional in version 2*,
because an optional record of what ran is a record that can omit the command that failed.

**Consequence to expect.** The matrix safety rule now grades every recorded command rather than the
first, so a mutating command in second position is caught.

**Extended 2026-08-24.** `command` remains the first of `commands` whenever both are present,
including on blocked stages; the validator used to skip that alias check on every
non-executed stage. A command that did not exit now carries `timed_out` instead of a
fake `exit_status`; see [A deadline-killed command is marked timed out, not given a
fake exit status](#a-deadline-killed-command-is-marked-timed-out-not-given-a-fake-exit-status).

**Revisit when.** A command entry needs a third ending besides `exit_status` and `timed_out`.

**Refs.** `schemas/compatibility-matrix.schema.json`,
`scripts/check_compatibility_matrix.py` (`check_record_version`), `scripts/assess_clients.py`.

### Raw client output is kept for the operator and kept out of the record

**Author.** Jeff Cox and Claude

**Decision.** Each command's stdout and stderr are retained, bounded at 64 KiB with truncation marked,
in a private `transcript.json` written into the run workspace. The public compatibility record never
quotes it and never names its path. The operator writes each row's `version`, `reason`, and `evidence`
from that transcript.

**Rationale.** The public record carries field names, counts, and comparisons — raw client output is
none of those and is not redacted. But discarding it left the operator nothing to write the record
*from*, which meant the scripted method could not produce the matrix the prose method did. Both
constraints are real; they are satisfied by two artifacts, not by one compromise.

**Rejected alternatives.** *Putting bounded output in the record*, because it is unredacted by
construction. *Printing it to the terminal only*, because a ten-client run's output does not survive
a scrollback. *Keeping it unbounded*, because one loud client should not fill the operator's disk.

**Consequence to expect.** The run workspace holds site-identifying text and must not be committed.
The runbook and `--workspace` help both say so.

**Revisit when.** A redaction pass over raw output becomes trustworthy enough to put a bounded
excerpt in the record itself.

**Refs.** `scripts/assess_clients.py` (`CommandTranscript`, `transcript_path`),
`docs/runbooks/portable-plugin-port.md`.

### Package identity is a descriptor under `ports/`, not a constant in a tool

**Author.** Jeff Cox and Claude

**Decision.** Every portable package carries one JSON descriptor at
`ports/<package>.json` holding its identity, its package root, its upstream source, its
custody table, its assessment settings, and the provenance notes its `PROVENANCE.json`
is generated from. `scripts/sync_vendor_source.py` takes `--package NAME`;
`scripts/check_compatibility_matrix.py` resolves the package from the record's own
`$.package.name`; `scripts/assess_clients.py` reads the entrypoints, skill units, and
credential prefixes from the same file. `scripts/port_config.py` is the single authority
for the format and validates it. `scripts/check_repo.py` fails when a descriptor does
not load or names a tree that does not exist.

This closes the revisit condition recorded under "Bind a current matrix to the tree it
assessed": the single `PACKAGE_ROOT` constant is now per-record.

**Rationale.** The pilot's runbook had to tell the next porter which constants to reach
into inside which two scripts. That is an instruction that rots, and it made "is this
tool generic?" a question about someone's diligence rather than about the code. As data,
the same information is validated on load, checked by the repository gate, and readable
by a third tool that did not exist when the first two were written.

The descriptors live *outside* `plugins/` deliberately. A compatibility matrix binds to a
fingerprint of the package tree, so a descriptor stored inside the tree it describes would
move that fingerprint whenever the tooling's configuration changed and invalidate
assessment evidence that is still true.

**Rejected alternatives.** *A second JSON schema file describing the descriptor*, because
a rule written twice is a rule that can disagree with itself; `port_config.py` validates
and `tests/test_port_config.py` derives its corpus from that module. *A descriptor inside
the package*, for the fingerprint reason above. *Defaulting `--package` to the first
package*, because a tool that overwrites a tree and deletes stale paths inside it should
name the tree out loud, and a default makes the first-ported package the silent one.
*Deriving the matrix's package root from a CLI flag rather than from the record*, because
the record already names the package it assessed and a flag lets the two disagree.

**Consequence to expect.** Porting a package is a new descriptor plus a review of it,
rather than edits inside two scripts. A descriptor with an empty
`assessment.package_scripts` would scope the mutating-operation safety rule to nothing,
which is a fail-open; a test asserts the shipped list names files the package carries.

**Revisit when.** A third tool needs package-specific settings that do not fit these
fields, or a package needs two descriptors (two upstream sources into one tree).

**Refs.** `scripts/port_config.py`, `ports/README.md`, `tests/test_port_config.py`,
[the queued Fleet Core target](QUEUED.md).

### The ten-client assessment is a program, and it refuses rather than guesses

**Author.** Jeff Cox and Claude

**Decision.** `scripts/assess_clients.py` carries the ten-client roster, the four stages,
and every client quirk. It runs nothing unless `--execute` is passed; it strips the
package's declared credential variables from every subprocess; it routes every stage argv
through `check_compatibility_matrix.command_safety_problems` *before* starting the
process; it gives every stage a deadline; it refuses a state-writing stage under the
operator's own home and refuses the isolated-only client a real home outright; and it
refuses to emit a record at all if the assessed tree moved during the run.

The record it emits is deliberately incomplete: each client's `reason` is empty, and
`check_compatibility_matrix.py` refuses a row with no concrete reason. A record no one
finished reading therefore cannot be committed as evidence.

**Rationale.** The status a harness computes is a proposal from stage results. The reason
is a claim about *why*, which only the person who watched it can make. Filling it in
automatically would produce records that pass every check and assert things nobody
observed — the precise failure the fingerprint binding exists to catch, moved one level up.

**Rejected alternatives.** *Executing by default*, because the first thing this program
does is install software into directories. *Deriving the overall status and stopping*,
because a status without a reason is not evidence. *Recording a client's actionable
refusal as `blocked`*, because the attempt ran and the client named the missing artifact;
that is the Codex row's entire value. *A second copy of the mutating-operation predicate
inside the harness*, because a rule enforced before the fact by one copy and after the
fact by another can be satisfied by neither when they disagree.

**Consequence to expect.** A stage whose client is not installed is `blocked` with the
binary named, never a package failure. A stage that hits its deadline is `blocked` with
the deadline named.

**Revisit when.** A client needs a stage vocabulary the four stages cannot express, or the
roster changes.

**Refs.** `scripts/assess_clients.py`, `tests/test_assess_clients.py`,
[the stdin learning](LEARNINGS.md#a-harness-that-inherits-stdin-behaves-differently-in-a-terminal-than-under-a-scheduler).

### Review rounds are bounded at three, and a round's repairs ship as one release

**Author.** Jeff Cox and Claude

**Decision.** A port under independent review gets at most three review rounds
against a frozen candidate. Every confirmed finding from a round is batched into a
single repair and a single release, and the fingerprint-bound evidence is re-run
once per round rather than once per defect. If the third round still returns
`repairs_requested`, work stops and the residual findings go to the operator with
their evidence, rather than a fourth round beginning on the coordinator's own
authority.

**Rationale.** The UniFi pilot ran nine rounds and shipped one defect per release.
Because the compatibility matrix and the post-activation readback are bound to the
package fingerprint by test, each release invalidated both: nine ten-client matrix
runs and eight readback captures for one port. Batching cycles 4 through 8 into
one repair per round would have produced roughly two of those runs instead of six.

The round bound is a separate lever from the batching and addresses a different
failure. Rounds four through nine were all one rule, and the coordinator kept
authorising its own next attempt because each round produced a real finding. A
real finding is not evidence that another unattended round is the right response;
after three, the operator is better placed to judge whether the rule needs a
different approach than another repair.

**Rejected alternatives.**

- *Leave both unbounded, as the pilot ran.* This is the status quo that produced
  the numbers above. Its one merit — every defect found is fixed immediately — is
  preserved by batching, which fixes them all, just together.
- *Bound the rounds but keep per-defect releases.* Keeps the evidence multiplier,
  which is where the mechanical time actually went.
- *Weaken the fingerprint binding so evidence survives a byte change.* Rejected
  outright. That binding caught stale evidence repeatedly across the pilot and is
  the reason the final record can be trusted. The cost is real and the answer is
  fewer releases, not weaker evidence.
- *Batch across rounds as well, reviewing only once at the end.* Discards the
  independent check on each repair, which is what caught the two class-level
  defects.

**Exception.** A confirmed fail-open in a security rule is repaired and re-reviewed
on its own, not batched. Holding a known-exploitable gap to fill a batch trades
the wrong thing.

**Revisit when.** A port hits the three-round bound twice, or a round's batch grows
large enough that a reviewer cannot attribute a regression to a specific repair. The
first says the bound is too tight for the work; the second says the batch is too
coarse, and the batch should split before the bound moves.


## 2026-08-22

### Compatibility evidence is captured on the floor interpreter, by explicit path

**Author.** Jeff Cox and Claude

**Decision.** Every command in the compatibility matrix's invocation stage and in
the post-activation readback runs on the interpreter the catalog declares as its
minimum — `python3.12` today — named by explicit path, never as `python3`. The
recorded commands say `python3.12` so a reader can see which interpreter produced
the numbers.

**Rationale.** The catalog declares `python>=3.12`. Evidence gathered on a later
interpreter supports a claim about that later interpreter and nothing about the
floor. This is not hypothetical here: the two superseded matrices ran on CPython
3.14 and recorded 29 and 21 lines of usage text, where the floor interpreter
prints 30 and 22 for the very same bytes. Had a floor break existed, the same
setup would have reported green.

**Rejected alternatives.**

- *Run on `python3` and note the version in prose.* This is what the earlier
  matrices did, and both had to add a paragraph saying the floor case was not
  shown. A limitation that has to be written down every time is a defect in the
  method, not a caveat.
- *Run on both the floor and the default interpreter.* Twice the stages for a
  claim nobody makes. Every later interpreter is in contract by construction; the
  interesting boundary is the minimum, and only the minimum is promised.
- *Add a `python_version` field to the matrix schema.* The schema is closed by
  design and its `method` object is closed too. The interpreter is recorded in
  `method.isolation` and in every invocation stage's evidence string, which keeps
  one schema rather than growing one per fact.

**Revisit when.** The declared floor moves. The floor lives in
`tests/test_python_floor.py` as `PYTHON_FLOOR`; when it changes, the interpreter
used to capture evidence changes with it, and the evidence has to be re-captured
rather than re-labelled.

### The portable catalog's minimum supported Python is `python>=3.12`

**Author.** Jeff Cox and Claude

**Decision.** The portable catalog declares a minimum supported Python of
`python>=3.12`. This is a minimum, not a pin: every later interpreter is in
contract, and nothing here promises 3.10 or 3.11 any more. Raising the floor
above 3.12 is a separate operator decision and is not taken here.

The floor is stated once, as the constant in
[`tests/test_python_floor.py`](../../tests/test_python_floor.py), and every
place the catalog declares it is checked against that constant: the
continuous-integration interpreter pin in
[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml), the repository
[`README.md`](../../README.md), the
[pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md),
the Fleet Core package [README](../../plugins/fleet-core/README.md) and
[changelog](../../plugins/fleet-core/CHANGELOG.md), and this entry. A portable
skill that declares a `compatibility` value must declare this one. The gate also
fails when any of those files stops stating a floor at all, so the check cannot
be defeated by deleting a declaration, and it fails on any `python>=` version
token anywhere in the repository that names a different version.

The ported-plugin continuous-integration job now pins `3.12` rather than `3.10`,
because a floor that is never exercised is not a floor and the only interpreter
that job can usefully prove is the lowest one the contract admits.

**Rejected alternatives.** *Keeping a 3.10 floor and repairing the import
upstream.* The one-line upstream repair is real and available, but it answers
the wrong question. Nothing ever proved a 3.10 floor: the ten-client
compatibility assessment ran every stage on an interpreter well above it, so the
3.10 case was never observed, and the claim rested on reading the lowest
interpreter the ported bytes happened to parse under. Repairing this import
would restore a promise the catalog still could not keep and would leave the
next 3.12-era API to break it again.

*Pinning exactly 3.12.* That would refuse interpreters the authoritative source
supports and would turn every later Python release into a catalog-wide edit.

*Moving the floor to 3.11, the minimum the broken import actually required.*
That is a floor derived from one accident of one byte copy rather than from the
source's own contract, and it would have to move again on the next one.

*Leaving the declarations as separate hand-maintained strings.* The floor was
already stated in at least five places and had already fallen out of agreement
with the code it described. Prose that is not checked is not a contract.

**Rationale.** The authoritative source repository,
`infiquetra-claude-plugins`, declares `requires-python = ">=3.12"` in its
project file and pins `python-version: "3.12"` in every one of its
continuous-integration jobs. Both statements were read at commit `ed72f439`,
the revision both packages in this catalog are derived from, and at the head of
that repository's default branch. A derived catalog must not promise more
compatibility than the source it is derived from. Where it does, the promise is
not merely unproven, it is unprovable: this repository does not own the bytes,
cannot test them on the interpreter it advertises, and inherits whatever
interpreter requirement upstream adopts on the next synchronization.

This cycle demonstrated the failure end to end. Re-synchronizing the Fleet Core
slice to 0.25.1 brought in `from datetime import UTC`, which exists only on
Python 3.11 and newer. The digest check passed, because the bytes really were
identical to their source; the derived package silently stopped running on the
floor its own documentation advertised. Aligning the floor with the source
removes the class of failure rather than the one instance of it.

**Supersedes.** The plan's KTD7 in its original form, which derived a 3.10 floor
from a bare union annotation evaluated at definition time. That reasoning is
preserved in the plan rather than deleted. It established a lower bound on what
the ported code parses under; it was never a statement of what the catalog
supports, and the two came apart on the first re-synchronization.

**Known gap, recorded rather than closed.** KTD7 also claimed the floor is
declared in the skills' `compatibility` frontmatter. It never was, and it cannot
be added here: both portable `SKILL.md` documents are classified
`upstream-byte-copy`, so an added field would break digest equality with their
source and would move the assessed package's tree fingerprint, retiring the
ten-client matrix bound to it. Nothing under `plugins/unifi/` was touched by
this decision for that reason. The declaration is
[queued as upstream work](QUEUED.md).

**Revisit when.** The authoritative source raises or lowers its own
`requires-python`, or this catalog acquires a package whose source declares a
different floor from the rest — at which point one catalog-wide floor stops
being the right shape and the check has to become per-package.

**Refs.** [Pilot plan KTD7](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md),
[the floor gate](../../tests/test_python_floor.py),
[the learning this decision answers](LEARNINGS.md#a-byte-copy-imports-the-upstream-platform-floor-along-with-the-upstream-fix),
[the archived queue item](ARCHIVE.md#decide-the-python-floor-the-fleet-core-resync-raised)

---

### The ported test's pytest guard raises SkipTest instead of binding pytest to None

**Author.** Jeff Cox and Claude

**Decision.** The `guard-pytest-import` deterministic transform over
`tests/test_retry_backoff.py` moves to version 2. Where version 1 bound the name
`pytest` to `None` when the dependency was absent, version 2 raises
`unittest.SkipTest`. Everything else about the rule is unchanged: the upstream
module docstring is still replaced with one recording the port, and every line
from `class RateError(Exception):` to end of file is still copied byte for byte.

**Rejected alternatives.** Keeping version 1, because Fleet Core 0.25.1 brought
two tests carrying `@pytest.mark.parametrize` and a decorator is evaluated when
the module is imported: against `None` it raises `AttributeError`, so the
dependency-free baseline job would fail on a module it never intended to run.
Substituting a hand-written stub object exposing `mark.parametrize` and
`raises`, because a fake that silently absorbs whatever the upstream suite
reaches for is a lie in a file whose entire purpose is to be a faithful copy,
and it would need extending every time upstream uses one more pytest feature.
Dropping the ported test from the hermetic job by renaming it out of the
`test*.py` pattern, because the discovery pattern is not this package's to
redefine and a test nothing collects is a test nobody notices breaking.

**Rationale.** `unittest` catches `SkipTest` raised during module import and
records the module as one skipped test, so the baseline job stays green, exits
0, and says out loud why it collected nothing there — verified directly rather
than assumed. The plugin job, where pytest is installed, runs all eighteen test
functions unchanged, which pytest expands to twenty-five cases. The guard also
stops being a maintenance liability: it no longer has to be revisited each time
upstream reaches for another pytest feature at module scope.

**Revisit when.** The hermetic baseline job gains pytest, which would make the
guard dead code, or upstream splits its suite so the ported half no longer needs
pytest at all.

**Refs.** `plugins/fleet-core/PROVENANCE.json` (removed 2026-09-22; see [CHANGELOG.md](../../plugins/fleet-core/CHANGELOG.md)),
[the 0.25.1 changelog entry](../../plugins/fleet-core/CHANGELOG.md)

### A re-synchronization does not renumber the evidence it invalidates

**Author.** Jeff Cox and Claude

**Decision.** The Fleet Core 0.25.1 re-synchronization left
[`docs/evidence/2026-08-22-unifi-compatibility-matrix.md` (superseded)](../evidence/2026-08-22-unifi-compatibility-matrix.md)
and
[`docs/evidence/2026-08-22-unifi-post-activation-readback.md` (superseded)](../evidence/2026-08-22-unifi-post-activation-readback.md)
untouched, and shipped with the eight binding tests over them failing. The
recorded fingerprints still name the tree those assessments actually ran
against.

**Rejected alternatives.** Writing the new tree digest into both documents,
because the matrix states the rule in its own text — "Refreshing the numbers
without re-running the assessment is precisely the failure this binding exists
to catch" — and doing it by hand rather than by a flag does not make it a
different act. It would turn forty observed stage results and ten client
readbacks into claims about bytes nobody ran. Marking the current matrix
superseded, because the supersession contract requires a named successor that is
itself current, and no successor exists until someone re-runs the ten clients.
Reverting the bundle regeneration to keep the digest still, because a consumer
carrying a stale copy of a repaired rate-limit primitive is the actual defect
this whole re-synchronization exists to remove.

**Rationale.** The binding is not misfiring. Bundling puts a stamped Fleet Core
module inside the UniFi package, so a Fleet Core release necessarily changes the
UniFi tree digest, and the document correctly reports that it no longer
describes what ships. Red is the accurate state, and a red check that names real
work still owed is worth more than a green one bought by editing the number
under comparison.

**Revisit when.** The operator authorizes the ten-client re-run and the
post-activation readback; the new matrix is published as current and the present
one is marked superseded by it, which is the only path that clears these eight
tests honestly.

**Refs.** [Queued evidence re-run](QUEUED.md#re-run-the-ten-client-matrix-and-the-readback-against-the-resynced-package),
[the learning](LEARNINGS.md#regenerating-a-build-artifact-retires-the-observational-evidence-bound-to-it)

### The portable UniFi README is target-owned, rewritten site-neutral

**Author.** Jeff Cox

**Decision.** `plugins/unifi/README.md` is target-owned portable source. It
describes this package: the Agent Plugins 1.0 layout, the
`com.infiquetra.claude/` client extension directory, the Fleet Core bundle,
site-profile resolution, and commands that run in this repository. It is not
an upstream byte copy of the Claude plugin README, and it is not produced by a
deterministic transform of that file.

**Rejected alternatives.** Keeping the file as `upstream-byte-copy`, because
that is the classification that shipped Cursor F-07: a consumer opening the
portable package's own documentation was told it was a Claude Code plugin and
was given pytest paths this repository does not contain. Authoring a
`portable-readme` transform in `scripts/sync_vendor_source.py`, because that
script is owned by the concurrent C8 repair (path-safety) and a transform
would still be defined over a Claude-specific source document whose subject is
the wrong package. Repairing the upstream README so a byte copy becomes
portable, because this run must not edit another repository.

**Rationale.** The pilot plan already assigned the README "portable core,
rewritten site-neutral". Claude-only installation belongs in the adapter
directory. A later `synchronize()` that still lists `README.md` in
`PORTABLE_BYTE_COPIES` would restore the Claude lede; `tests/test_unifi_readme.py`
fails closed on that restoration (lede identity, absent test modules, and the
provenance classification). Dropping the path from the sync table is queued
rather than taken here, because that tuple lives in a file this unit does not
own.

**Revisit when.** The next UniFi synchronization is authorized, or the C8 unit
(or a follow-up) removes `README.md` from `PORTABLE_BYTE_COPIES` so a
deliberate resync preserves the portable README instead of fighting the test.

**Refs.** [Queued sync-table residual](QUEUED.md#drop-readme-from-the-unifi-byte-copy-table-so-a-resync-keeps-the-portable-docs),
[byte-copy README learning](LEARNINGS.md#a-byte-copied-readme-describes-the-source-package-not-the-derived-one),
[pilot plan custody table](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)

---

### Pause the pilot at the compatibility matrix and take no client-specific remediation

**Author.** Jeff Cox and Claude

**Decision.** The portability pilot stops at the completed ten-client compatibility
matrix. Two clients did not consume the portable package: OpenAI Codex is recorded as
works through an adapter, and Cursor Agent is recorded as failed. Neither is repaired
here. Whether a given client warrants a repair, an adapter, a different distribution path,
or an explicitly unsupported status is one operator decision per client, and each is taken
separately from this work. The package-side defect that leaves the assembled package with
no working entrypoint is recorded in the same way and is likewise not repaired here.

**Rejected alternatives.** Building the Codex marketplace manifest immediately, because
the matrix would then be reporting on a package that had been changed to make it pass, and
the assessment exists to say what was true of the package as assembled. Dropping the two
non-consuming clients from the matrix, because coverage was the deliverable and a client
recorded as unsupported or failed with its reason is a result, not a gap. Repairing the
missing bundle inside this unit, because a defect found by an assessment is scope the
assessment discovered, not scope it was granted.

**Rationale.** Implementation scope that expands itself the moment it finds a problem
stops being a scope. The matrix was built to inform a decision, and taking the decision
inside the same unit that produced the evidence removes the operator from a choice that is
theirs. Coverage was mandatory and passing was not, which is only true if failures end in
a pause rather than in a repair.

**Revisit when.** The operator has taken the per-client decisions, or the package
entrypoint defect is separately authorized for repair.

**Refs.** [Compatibility matrix (superseded)](../evidence/2026-08-22-unifi-compatibility-matrix.md),
[pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md),
[per-client queued decision](QUEUED.md#decide-per-client-what-follows-the-compatibility-matrix),
[queued entrypoint repair](QUEUED.md#emit-the-declared-fleet-core-bundle-so-the-package-has-a-working-entrypoint)

---

### Leave the portable profile resolution order at two rungs and close the Infiquetra gap in deployment

**Author.** Jeff Cox and Claude

**Decision.** The portable site-profile contract keeps resolving exactly two rungs, the
`UNIFI_SITE_PROFILE` environment variable and then the path remembered in `config.json`,
followed by no profile at all. The documented deployed runtime default,
`${XDG_CONFIG_HOME:-~/.config}/infiquetra/unifi/site-profile.json`, is not added as a
third rung by this work. The Infiquetra instance closes its own gap in the private
`home-lab` repository, where the Ansible deployment now also writes `config.json` so the
remembered rung resolves the file it just deployed. The general fix stays queued.

**Rejected alternatives.** Adding the default path as a final rung inside this pilot,
because it changes what an already-deployed host resolves and therefore touches the
portable contract, both consumers of it, and the Claude adapter's loader with their tests
— a contract change that deserves its own unit rather than a fix smuggled into a
documentation unit. Making the environment variable mandatory, which would delete the
optional-profile promise the contract exists to keep. Documenting the trap and leaving it
at that, because a documented trap is still a trap.

**Rationale.** The portable contract and the Infiquetra custody instance are separable on
purpose. This repository's normative documentation never presents the private `home-lab`
plus Ansible arrangement as required; it is one operator's deployment of an optional
profile. That separation is exactly what allows the operator's own gap to be closed in
their deployment today while the portable question stays open for a decision that affects
every other operator.

**Revisit when.** A second operator deploys a site profile on a host this repository does
not control, or the queued contract change is authorized.

**Refs.** [Queued contract change](QUEUED.md#the-documented-default-site-profile-runtime-path-is-never-read),
[seam learning](LEARNINGS.md#every-unit-passed-its-own-tests-and-the-defect-lived-in-the-seam-between-two-correct-units),
[site profile reference](../../plugins/unifi/references/site-profile.md)

---

### Keep a generated file's stamp outside the bytes it hashes

**Author.** Jeff Cox and Claude

**Decision.** A generated Fleet Core bundle carries two independent digests. The
source-payload digest covers the upstream module and detects a stale bundle whose source
has moved. The generated-output digest covers the generated file with its own stamp block
excluded, and detects a hand-edited output. `scripts/check_repo.py` reports the two as
different, deterministic failures.

**Rejected alternatives.** One digest over the whole generated file, which is
self-referential and cannot be computed, since the digest would have to appear inside the
bytes it covers. One digest over the source only, which would leave a hand-edited
generated file undetectable — the exact degradation that turns a generated artifact into
an unmaintained copy-paste fork.

**Rationale.** Stale source and tampered output are different problems with different
repairs. Collapsing them into one mismatch tells a maintainer that something is wrong
without telling them which thing, and a signal that needs investigation before it can be
acted on is a weak signal.

**Revisit when.** A second consumer bundles a Fleet Core module and the two-domain scheme
proves awkward, or a generated artifact appears that has no stable stamp location.

**Refs.** [Bundle declaration schema](../../schemas/fleet-bundle.schema.json),
[pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)

---

### Keep repository validation standard-library-only and give the ported plugin tests their own job

**Author.** Jeff Cox and Claude

**Decision.** Continuous integration runs two jobs. The repository validation job installs
nothing and runs `python3 scripts/check_repo.py`, the unittest suite, and `git diff
--check`, so the repository's own baseline uses the standard library alone. A second job
pins the catalog's declared floor, `python>=3.12`, installs `requests`, `urllib3`, and
`pytest` on it, and runs the ported plugin tests. Neither job ever contacts a UniFi controller, and the compatibility matrix is
produced by an operator-run assessment rather than by continuous integration.

**Rejected alternatives.** Rewriting the existing pytest tests into unittest so a single
job could run everything, which would discard proven upstream coverage for no behavioral
gain. Installing dependencies in the one existing job, which would make a package index
outage able to break validation of documentation-only changes.

**Rationale.** The repository's fast hermetic baseline is worth protecting as its own
guarantee: it answers whether this repository is internally consistent, using nothing it
has to download. The ported plugin tests answer a different question and legitimately need
third-party packages, so they get a job whose failures mean what they say.

**Amended 2026-08-22.** The second job's interpreter was pinned to 3.10 when this decision
was written. It now pins the catalog's declared floor, `python>=3.12`, under
[the floor decision](#the-portable-catalogs-minimum-supported-python-is-python312). The
two-job structure this entry decided is unchanged; only the pinned version moved.

**Revisit when.** The ported packages acquire a dependency the second job cannot install,
or the repository grows a project file that makes a single job hermetic again.

**Refs.** [Pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md),
[deferred Fleet Core inventory](../../plugins/fleet-core/DEFERRED.md)

---

### Reclassify both UniFi clients as a deterministic transform rather than a byte copy

**Author.** Jeff Cox and Claude

**Decision.** The two client scripts,
`skills/unifi-network/scripts/unifi_network_client.py` and
`skills/unifi-protect/scripts/unifi_protect_client.py`, move from **upstream byte copy**
to **deterministic transform** under requirement R4's three-way path classification. The
rule is `resolve-bundled-fleet-module`, version 1: it matches the single upstream block
that puts the client's own directory on `sys.path`, imports `fleet_commons_shim`, and
calls `fleet_commons_shim.load(NAME)`, and re-emits it as an insertion of the `_bundled/`
directory beside the client followed by a direct `import NAME`. The rule reads the module
name and the binding out of the source rather than assuming them, changes no other byte,
and raises rather than proceeding when the block is absent or appears more than once.
`plugins/unifi/fleet-bundle.json` declares a destination beside each client, which is
where the pilot plan's assembled-package tree already put the generated bundle.

**Rationale.** The portable package drops both `fleet_commons_shim.py` copies, because
their resolution ladder is Claude-specific runtime discovery the portable package must
not retain. A byte copy of a client that imports a module the package does not carry
aborts at module scope, so the package had no working entrypoint on any client. The
byte-copy rule is not a rule about bytes for their own sake: it exists so a downstream
edit cannot become an unrecorded second source. A versioned rule over the pinned upstream
bytes, with the source digest, the output digest, and the rule text in the provenance
manifest, satisfies that purpose exactly -- the output is reproducible from the source
alone, and re-synchronization re-applies the rule rather than silently restoring the
broken import.

**Rejected alternatives.**

- *Repair it upstream first, as the pilot does for every other divergence.* Upstream is
  a Claude package where `fleet_commons_shim` is present and correct. There is no
  upstream defect to repair, so this would mean degrading the Claude package to suit the
  portable one.
- *Copy `fleet_commons_shim.py` into the portable package.* Prohibited: the operator's
  Fleet Core amendment forbids retaining Claude-specific runtime discovery.
- *Require a `FLEET_COMMONS_ROOT` environment variable, or an Agent Plugins dependency
  field.* Both prohibited by the same amendment. The artifact must be complete at install
  time, with no separate Fleet Core installation.
- *Leave the clients as byte copies and document them as not executable.* This is what
  the package already did. A portable package with no runnable entrypoint is not a
  portability result.

**Revisit when.** Upstream stops importing `fleet_commons_shim` at module scope, or moves
to a mechanism the portable package can carry unchanged. The transform then has no input
to match and refuses to synchronize, which is the deliberate signal to revisit rather
than a failure to work around.

### Guard the join between the bundler and the synchronization in the validator, not only in tests

**Author.** Jeff Cox and Claude

**Decision.** `scripts/check_repo.py` gains `check_fleet_bundle_outputs`, which rejects a
module a consumer's `fleet-bundle.json` declares but no generated bundle carries, and any
file under a `_bundled/` directory that no declaration accounts for. The presence half of
`scripts/bundle_fleet_module.py --check` is factored into `presence_errors` so both
commands report the same two conditions from one implementation. Alongside it,
`tests/test_client_entrypoints.py` runs each shipped client's `--help` in a subprocess,
with third-party transport stubbed and every `UNIFI_*` variable removed, and separately
asserts that deleting the generated bundle from a copy of the package breaks every
entrypoint.

**Rationale.** `check_bundled_files` reads bundles that exist, so a bundle that was never
generated is invisible to it. That is how the repository reported success while shipping
two clients importing a module nothing had written. A validator that only inspects
present files cannot catch an absent one; the declaration is the statement of what should
be present, so comparing the two is the missing assertion. The subprocess test is the
independent signal: it fails whether the cause is the declaration, the transform, or the
bundler.

**Rejected alternatives.**

- *Reuse `check_consumer` wholesale inside `check_repo`.* It also re-checks the stamps,
  which `check_bundled_files` already owns, so one tampered bundle would be reported
  twice in different vocabulary.
- *Rely on the entrypoint test alone.* A test proves the shipped tree works today; the
  validator states the invariant, and continuous integration runs it in the hermetic
  standard-library-only job.

**Revisit when.** A consumer needs a generated bundle outside a `_bundled/` directory,
which would make the directory name the wrong discriminator.

### Detect credentials by value with two narrow families, and never by bare entropy

**Author.** Jeff Cox and Claude

**Decision.** `scripts/check_repo.py` now rejects a credential written as a *value*
anywhere under `plugins/`, using exactly two detection families. The first is a list of
literal credential formats — AWS access key ids, GitHub and Slack and Stripe tokens,
Google and Anthropic and OpenAI API keys, JSON web tokens, private key blocks, and
credentials embedded in a URL — matched in every text file of a package including source,
because a real key committed into source is a leak whatever the surrounding code does with
it. The second is a credential-shaped key (`password`, `secret`, `token`, `api_key`,
`bearer`, `client_secret`, and their near neighbours) assigned a value of at least six
characters that clears 2.5 bits of entropy per character and is not a placeholder or a
reference to where the secret actually lives. The second family runs only on data and
documentation files, never on source.

**Rationale.** The reviewers' finding is that every existing guard — the site profile
loader, its schema, and the compatibility matrix redaction check — inspects field *names*,
so a password pasted into an allowed `notes`, `description`, or `ownership` value passes
all of them. Closing that needs value inspection, and value inspection is worth having
only if it is quiet enough to stay switched on. Measured against the live package tree,
this rule produces zero false positives while still reporting the reviewer's own example,
`notes: "controller password=hunter2"`.

**Rejected alternatives.** A third family scanning for bare high-entropy strings, which is
the usual approach and is unusable here: a provenance manifest is nothing but sha256
digests, so it would fire on every package in the catalog and the gate would be turned off
within a day. Running the credential-assignment family on source as well, which was
measured before being rejected — it produced five false positives on the shipped package,
every one of them credential-*handling* code such as `api_key = (api_key or "").strip()`
and `"X-Api-Key": self.api_key`, and none of them a secret. Scanning the whole repository
rather than `plugins/`, which would make `docs/reviews/` a continuous integration failure
surface; those two reviewer reports are immutable evidence with recorded digests, they
quote credential-shaped text on purpose, and a gate no one is allowed to satisfy is a gate
that gets deleted. `plugins/` is also the scope every other package check here already
uses, and it is the tree that actually leaves this repository.

**Accepted limits.** A short, low-entropy secret in a free-text value still passes:
`password: secret` is six characters of 2.25 bits and is below the floor by design. So
does a secret in a package file that is neither text nor a recognised data suffix. This
check is defense in depth against an accident, not a proof of absence, and the operator
guarantee should be worded as such.

**Revisit when.** A credential format in use by the fleet is not on the list, a real
credential reaches a package and this check does not report it, or the false-positive rate
stops being zero on the live tree.

**Scope note.** This closes the repository gate only. The same finding also implicates
`plugins/unifi/scripts/site_profile.py`, whose `validate_profile` accepts a credential in
a `notes` value at runtime, and `scripts/check_compatibility_matrix.py`, whose redaction
check is name-shaped. Neither file is owned by this unit and neither is changed here.

### Bind a current matrix to the tree it assessed, and make supersession the only exemption

**Author.** Jeff Cox

**Decision.** `scripts/check_compatibility_matrix.py` recomputes the fingerprint of
`plugins/unifi/` on every run — package name, version, file count, and a tree digest over
the sorted per-file digests *with their relative paths* — and fails when the record does
not match. A document may exempt itself only by declaring `<!-- matrix-status: superseded -->`
alongside a `superseded-by` naming an existing current matrix and a `superseded-reason`.
A superseded document whose fingerprint still identifies the shipped tree is rejected.
`matrix-status` defaults to `current`, so the binding is fail-closed. The no-argument run
validates every matrix document in `docs/evidence/`, superseded ones included.

**Rejected alternatives.** *Refreshing the numbers only*, because that leaves the identical
trap armed for the next package change and the review named this explicitly. *Adding a
`superseded` field to the record*, because `schemas/compatibility-matrix.schema.json` is
closed and owned by no unit in this run; HTML comment directives carry document-level
metadata without a schema change. *Dropping the JSON fence in the retired document so the
validator skips it*, because retiring a document withdraws its claim about the current
package, not the coverage and redaction rules it was published under. *Overwriting the
original matrix in place*, because the assessment happened and its record is evidence.
*A `--update` flag that rewrites the record from the tree*, because a one-keystroke refresh
would let a stale matrix pass by editing the evidence to match; there is a read-only
`--print-fingerprint` and nothing that writes. A test asserts no such flag is added.

**Rationale.** Hashing the per-file digests alone would leave a pure rename invisible, and
a rename is exactly the drift a binding exists to catch, so relative paths are inside the
hashed text. Checkout noise — `__pycache__`, `.pyc`, `.DS_Store` — is excluded, because a
fingerprint that moved when the test suite ran would be abandoned within a week. The digest
is defined in prose in the matrix itself so a third party can reproduce it from published
bytes.

**Consequence to expect.** Any future change under `plugins/unifi/` fails
`python3 scripts/check_compatibility_matrix.py` and the test suite until the assessment is
re-run and the record refreshed. That is the intended cost: the check is meant to be
noticed, and re-running forty credential-free stages is roughly an hour.

**Revisit when.** `schemas/public-evidence.schema.json` lands and can carry document status
as a schema field, or a second package joins the catalog and the single `PACKAGE_ROOT`
constant needs to become per-record.

**Refs.** [Digest learning](LEARNINGS.md#a-digest-in-an-evidence-record-proves-nothing-until-something-recomputes-it),
`scripts/check_compatibility_matrix.py`, `tests/test_check_compatibility_matrix.py`.

## 2026-08-21

### Choose UniFi plus a portable Fleet Core slice as the first portability pilot

**Author.** Jeff Cox and Claude

**Decision.** Port the Claude `unifi` plugin into a portable Agent Plugins 1.0 package
in this repository, together with a new portable Fleet Core source carrying only the
`retry_backoff` module. The Claude repository is repaired first, released second, and
synchronized from third. Custody does not move.

The load-bearing choices, each recorded in full in the
[pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md):

- The portable copy is derived and digest-verified, never a second writable source.
- The authoritative source is repaired before the port consumes it; downstream-only
  correction and intentional target divergence are both rejected.
- Extract means relocate, not delete: the embedded lab topology moves into an operator
  site profile, and the repaired release is gated on that replacement path being
  verified so the Claude agent never loses site context.
- Fleet Core becomes a first-class portable source, but only one vertical slice is
  ported; the required module is bundled into consuming artifacts at build time, since
  Agent Plugins 1.0 has no dependency mechanism.
- Compatibility coverage across all ten installed clients is mandatory; passing is not.
  The matrix is a deliverable ending in an operator pause, not a release gate.

**Rejected alternatives.** A hand-port with no drift detection; a subtree or submodule of
the vendor repository; porting the documentation defect verbatim; inlining the retry
primitive and reversing the fleet-wide shared-primitive decision; inventing an Agent
Plugins dependency field; and requiring an environment variable that would resolve to
nothing on a non-Claude host.

**Rationale.** UniFi is small enough to finish and real enough to exercise the actual
architecture boundary. Investigation found three problems the file listing could not
show — an undeclared cross-plugin dependency resolved through Claude-specific discovery,
documentation describing capabilities removed five months earlier, and one operator's
controller address hard-coded as a universal default — and each of them is exactly the
kind of thing a pilot exists to surface before a larger port inherits it.

**Revisit when.** The ten-client compatibility matrix is complete and the operator has
made the per-client decisions that follow it, or evidence shows the build-time bundling
model does not generalize to a second consumer.

**Refs.** [Pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md),
[architecture brief](../cross-vendor-plugin-architecture-brief.md),
[superseded parity decision](ARCHIVE.md#void-parity-baseline-recorded-in-error),
[archived pilot item](ARCHIVE.md#choose-the-first-portability-pilot-and-custody-gate)

---

### Establish a public cross-vendor plugin source repository

**Author.** Jeff Cox and Codex

**Decision.** Use `infiquetra-agent-plugins` as the public repository for the
portable architecture, future shared plugin sources, and explicit vendor
adapters. Existing vendor repositories remain authoritative until a pilot is
proven and custody is moved by a later decision.

**Rejected alternatives.** `infiquetra-plugins` was too broad to distinguish
coding-agent capabilities from other plugin systems. Immediately replacing the
vendor repositories would create an unproved big-bang migration.

**Rationale.** The name identifies the domain, while the staged custody rule
allows shared sources to be proven without breaking current clients.

**Revisit when.** The first portable plugin passes its agreed compatibility
gate, or evidence shows the proposed repository boundary is wrong.

**Refs.** [Architecture brief](../cross-vendor-plugin-architecture-brief.md),
[archived pilot decision](ARCHIVE.md#choose-the-first-portability-pilot-and-custody-gate)

---

Keep newest entries first. When a decision is superseded, preserve the old text
in [ARCHIVE.md](ARCHIVE.md) and link the replacement.
