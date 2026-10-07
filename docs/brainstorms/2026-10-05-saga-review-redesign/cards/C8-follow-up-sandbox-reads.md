# agent-launcher: the targeted reviewer's sandbox reads only what the review needs

### Objective

Confine the targeted reviewer's sandboxed commands, merged in #187 for #158, to what the review
needs. Block reads of the whole home directory and allow back only the scratch copy, the packet and
the toolchain. Pass an allow-listed environment. Scrub secrets from proof output before it is
recorded or sent to Jev.

### Intent

The targeted reviewer runs tests from the change it reviews, inside Claude's command sandbox, set
through `--settings` by `reviewer_claude_settings`
(`plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py`). It is not called by any live
review yet: the single review command wires it in later. Three gaps, checked on `origin/main` at
218d828:

1. **Reads are blocked by a fixed list.** `denyRead` is `REVIEWER_CREDENTIAL_PATHS` (`launcher.py:2088`)
   plus extras (`:2197`): eleven paths such as `~/.ssh`, `~/.aws` and `~/.config/gh`. Anything else
   under the home directory stays readable.
   - On the operator's Mac that includes an Ansible vault password file, an `.env` of model-provider
     API keys and `~/.npmrc`.
   - Other common credential files are also missing from the list: `~/.git-credentials`, `~/.pypirc`,
     `~/.cargo/credentials*`, `~/.terraform.d`, `~/.vault-token`, `~/.config/hub` and
     `~/.local/share/keyrings`.
   - A hostile test in the reviewed change can read them.
2. **The environment is filtered by name.** `REVIEWER_CREDENTIAL_NAME`
   (`TOKEN|KEY|SECRET|PASSWORD|...`) hides only variables whose names look like credentials. A secret
   held in a variable with an ordinary name passes through.
3. **Proof output is sent unscrubbed.** The sandbox has no network, so a stolen secret cannot be sent
   anywhere directly. But a test can print it. The reproduction's output goes into the finding record,
   and `reviewer_answer.py` sends up to 4,000 characters of it to Jev (TypeSafe, a third-party service,
   `:432`) and to Langfuse.

The fix reverses the rule: block the whole home directory, and allow back only what the review needs.

### Out-of-scope / non-goals

- Other vendors' reviewer launches. Only Claude is staffed today, and other vendors are refused.
- The review-tools runner's untrusted-head fixes (the separate follow-up to #151).
- Changing the reviewer's prompt, answer schema or Jev verb.

### Files expected to change

- `plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py`
- `plugins/agent-launcher/tests/test_launcher_contract.py`
- `plugins/agent-launcher/CHANGELOG.md`
- `plugins/saga/scripts/reviewer_answer.py`
- `plugins/saga/tests/test_reviewer_answer.py`
- `plugins/saga/CHANGELOG.md`
- `docs/engineering-journal/DECISIONS.md`
- `docs/engineering-journal/LEARNINGS.md`

### Tests to add or update

- `test_launcher_contract.py`:
  - the reviewer settings' `denyRead` covers the home directory, and `allowRead` lists only the
    scratch copy, the packet and the named toolchain paths;
  - the sandboxed commands' environment holds only allow-listed names, so an ordinary-named variable
    carrying a value is absent;
  - the probe plants a canary file in the home directory outside the old list, and fails if it is
    readable.
- `test_reviewer_answer.py`:
  - proof output carrying fake tokens in known formats (a GitHub token, an AWS key ID, a private-key
    block, a long high-entropy string) reaches neither the record nor the Jev state;
  - each is replaced with a marker naming its kind.

### Context library links

- `docs/brainstorms/2026-10-05-saga-review-redesign/plan.md` (the targeted reviewer section)
- #158, #187

### Acceptance criteria

- [ ] AC-1: the reviewer's sandbox blocks reads of the whole home directory, and allows only the
  scratch copy, the packet and the toolchain paths it names. Proven by `python3 -m pytest
  plugins/agent-launcher/tests/test_launcher_contract.py -q --import-mode=importlib -k
  reviewer_read_confinement`.
- [ ] AC-2: sandboxed commands get only allow-listed environment variables. Proven by `-k
  reviewer_environment_allowlist`.
- [ ] AC-3: a live `python3 plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py
  reviewer-probe --vendor claude --model haiku` reports the new home canary unreadable, and exits 0.
- [ ] AC-4: known secret formats in proof output are replaced before the record is written and
  before the Jev state is built. Proven by `python3 -m pytest plugins/saga/tests/test_reviewer_answer.py
  -q --import-mode=importlib -k scrub`.
- [ ] AC-5: the agent-launcher and saga suites pass: `python3 -m pytest plugins/agent-launcher/tests
  plugins/saga/tests -q --import-mode=importlib`.

### Verification

```bash
python3 -m pytest plugins/agent-launcher/tests plugins/saga/tests -q --import-mode=importlib
python3 plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py reviewer-probe --vendor claude --model haiku
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
```

### Inputs inventory

- The operator's home directory and the credential files in it.
- The environment of the launching shell.
- The scratch copy of the reviewed change.
- The review packet.
- The interpreter, site-packages and toolchain paths the reviewed repository's tests need.
- Proof output written by the reviewer's commands.

### Failure modes / pre-mortem

- Blocking all of home breaks the reviewer's own test runs: an interpreter under `~/.local`, a uv
  cache or a node toolchain under the home directory. Guard: the probe runs a real Python test in
  the copy. The allow-list names each toolchain path with its reason.
- Claude's sandbox may not support an allow-back inside a blocked parent. Measure it first on the
  installed Claude Code version, as #187 measured the `//path` rule. If unsupported, stop.
- Scrubbing misses a format. Guard: the scrubber also catches high-entropy strings, and the record
  says when it replaced something.

### Stop conditions

- If Claude Code's sandbox cannot express "block home, allow these", stop and report what the
  installed version supports. Do not widen the list instead.
- Never read, print or copy the contents of a real credential file while testing. Use canaries.

### Risk

high

A hostile change under review could read the operator's credentials and print them into records
sent to a third-party service.
