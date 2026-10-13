# saga: the outcome job's schedule keeps running the plugin version that installed it

### Objective

Make the daily review-outcome job run the saga version currently installed, and make the setup survey report the
`outcome-schedule` step as not done when the installed schedule points at another version's script.

### Intent

`outcome_job.py install-schedule` writes a launchd plist whose script argument is the absolute path of the
`outcome_job.py` that ran the install (`script=str(Path(__file__).resolve())`). From an installed plugin that path
sits inside a version folder of the plugin cache, for example
`~/.claude/plugins/cache/<marketplace>/saga/<version>/scripts/outcome_job.py`. Claude Code keeps earlier version
folders after an upgrade (four saga versions sit side by side in one operator's cache today), so after a saga
upgrade the daily job keeps running the old version's code.

The setup survey cannot see this. The step's `done` check is `launchctl list com.infiquetra.saga.outcome-job`,
which succeeds whatever script the plist names, so `/saga:setup` and the setup pane report the step as done and
never offer to re-run it. A queue format change or a fix in a later release would silently not reach the job.

Found while reviewing #218, which made the step runnable from an installed plugin.

### Out-of-scope / non-goals

- Changing what the job does on each pass, its schedule time, or how it reads keys.
- Removing old version folders from the plugin cache; Claude Code owns that cache.
- Platforms other than macOS.

### Files expected to change

- plugins/saga/scripts/outcome_job.py
- plugins/saga/tests/test_outcome_job.py
- plugins/saga/references/setup-extensions.yaml
- plugins/saga/references/outcome-job.md
- plugins/saga/CHANGELOG.md

### Tests to add or update

- A test that `status` (or a new read-only check) exits non-zero when the installed plist's script path is not the
  `outcome_job.py` beside the running copy, and zero when it is.
- A test that the shipped `outcome-schedule` step's `done` vector uses that check, so a stale schedule reads as not
  done.
- A test that re-running `install-schedule` from a newer copy rewrites the plist to the newer script path.

### Context library links

_none_

### Acceptance criteria

- [ ] With a schedule installed from one plugin copy, the setup survey run from a second copy reports
  `outcome-schedule` as not done: `python3 -m pytest plugins/saga/tests/test_outcome_job.py` covers it.
- [ ] Running the step again from the second copy points the schedule at the second copy's script, and the survey
  then reports it done.
- [ ] `outcome-job.md` tells the operator to re-run the step after a saga upgrade only when the survey says so.

### Verification

```bash
python3 -m pytest plugins/saga/tests/test_outcome_job.py plugins/saga/tests/test_saga_setup.py
claude plugin validate --strict plugins/saga
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
```

### Risk

low

The change reads and rewrites one launchd plist the job already owns; the job's pass logic is untouched.

### Notes / conventions

Part of #147's follow-ups. The check must stay read-only and must not load or unload the launchd agent.
