# agent-launcher: the Claude reviewer's sandboxed commands see variables exported by shell start-up files

### Objective

Stop the targeted Claude reviewer's sandboxed commands from seeing environment variables that the operator's shell
start-up files export, and add that check to the Claude reviewer probe so the leak cannot return.

### Intent

While building #223, the builder added a start-up-export check to `launcher.py reviewer-probe`: an inert secret
exported by a shell start-up file must not reach the reviewer's sandboxed commands. Run against the existing Claude
recipe, the secret reached them. The Claude reviewer runs over the code under review, including its tests, so any
credential an operator exports from a start-up file is readable by that code during a review. Network is denied in
the Claude sandbox (the corrected network check passed), which narrows the exfiltration paths but does not close
them: a review's findings, transcripts and traces leave the sandbox.

#223 deliberately left the Claude recipe unchanged, because its card required that; this card changes it.

### Out-of-scope / non-goals

- The Grok and Muse recipes (#223 keeps both refused).
- Interactive Claude sessions; only the reviewer launch path changes.
- Editing the operator's shell start-up files.

### Files expected to change

- plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py
- plugins/agent-launcher/tests/test_launcher_reviewer.py
- plugins/agent-launcher/CHANGELOG.md
- docs/engineering-journal/LEARNINGS.md

### Tests to add or update

- The Claude reviewer probe includes the start-up-export check, using an inert secret and a scratch start-up file
  (never the operator's own files), and fails when the secret is visible to a sandboxed command.
- With the fix, the probe passes the start-up-export check and every check it passed before (18 of 18 at #223).
- A sandboxed command still sees the variables the reviewer's test reproduction needs, per the recipe's allow-list.

### Context library links

_none_

### Acceptance criteria

- [ ] `launcher.py reviewer-probe --vendor claude` fails on the unfixed recipe's start-up-export check and passes on
  the fixed one: `python3 -m pytest plugins/agent-launcher/tests/test_launcher_reviewer.py` covers both.
- [ ] A live Claude reviewer probe on this machine passes every check, including the new one.
- [ ] Saga's setup still reports the reviewer's test reproduction as available after the change.

### Verification

```bash
python3 -m pytest plugins/agent-launcher/tests/test_launcher_reviewer.py
python3 plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py reviewer-probe --vendor claude --model haiku
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
```

### Risk

high

The reviewer runs untrusted code; a wrong fix either leaves credentials readable or breaks the reviewer's test
reproduction.

### Inputs inventory

- The Claude CLI's sandbox and environment settings, read from its own `--help` and settings documentation on the
  build date.
- #223's start-up-export probe check and its evidence.

### Failure modes / pre-mortem

- Most likely: the fix filters the launch environment but the persistent shell re-reads start-up files inside the
  sandbox, so the probe must exercise the sandboxed shell itself, not the launch environment.

### Stop conditions

- The Claude CLI offers no way to keep start-up exports out of sandboxed commands: stop and report; do not weaken the
  probe.

### Notes / conventions

Part of #147; builds on #223 once it merges. Never print, log or write a credential.
