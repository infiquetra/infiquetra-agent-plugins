# saga: the cosmic-ray adapter reports no surviving mutants, because cosmic-ray 8.7.0 refuses saga's config and saga misreads its results

### Objective

Make saga's Python mutation adapter report cosmic-ray's surviving mutants correctly, and never report a run whose
mutants errored or never ran as a clean run.

### Intent

On 2026-10-12, cosmic-ray 8.7.0 (saga's pin) was installed on the operator's Mac, so
`plugins/saga/tests/test_review_adapters_python.py::test_cosmic_ray_live_records_a_survivor` ran for the first time. It
fails: for a repository whose only test asserts `True`, the adapter records no `surviving-mutant` finding. A diagnosis
found three faults in saga and one in the test:

- **No distributor.** `_invoke_cosmic` writes a config without a `[cosmic-ray.distributor]` table, which 8.7.0
  requires. `cosmic-ray exec` exits 78 with `ConfigKeyError('distributor')`, and the wrapper reports the run unfinished.
- **Wrong dump format.** With `name = "local"` added by hand, init and exec succeed and the dump holds 11 survived
  mutants at `app.py` line 2. 8.7.0 writes each dump line as a JSON array `[work_item, result]`, with the outcome at
  `result.test_outcome` and the position at `work_item.mutations[0].start_pos`. `_COSMIC_WRAPPER` skips every line that
  does not start with `{` and reads top-level `module`, `line` and `test_outcome` keys, so 11 survivors read as clean.
- **Errors dropped.** The wrapper keeps only `test_outcome == "survived"` and ignores `worker_outcome` values
  `exception`, `abnormal`, `no-test` and `skipped`, `incompetent` results, and pending (null) results. It runs no
  baseline, so a broken test command makes every mutant "killed" and the run looks clean.
- **The live test calls `python`.** `_installed()` reduces saga's command to a bare `python -c ...`; machines with only
  `python3` on PATH report the tool missing.

Unverified, for the builder to settle: in production saga runs `uv run --with cosmic-ray==8.7.0 python -c ...`; the
mutant workers' `python -m pytest` may then resolve to uv's temporary environment, which has no pytest, and every
mutant would be "killed".

### Out-of-scope / non-goals

- Other mutation tools (Stryker, cargo-mutants, muter, mutate4dart).
- Changing cosmic-ray's pin.

### Files expected to change

- plugins/saga/scripts/review_adapters_python.py
- plugins/saga/tests/test_review_adapters_python.py
- plugins/saga/CHANGELOG.md
- docs/engineering-journal/LEARNINGS.md

### Tests to add or update

- The generated config carries the distributor table, and `cosmic-ray exec` on it exits 0.
- A recorded 8.7.0 dump (array lines) yields one finding per survived mutant at the right path and line.
- A dump with an errored, abnormal, skipped, no-test, incompetent or pending mutant marks the run unfinished.
- A baseline failure (the test command fails on unmutated code) marks the run unfinished, not clean.
- The live test runs with `sys.executable` or skips when no usable Python is found, and passes on this machine.
- The production command's workers import pytest, proven by a test that fails if they resolve to an environment
  without it.

### Context library links

_none_

### Acceptance criteria

- [ ] `python3 -m pytest plugins/saga/tests/test_review_adapters_python.py -k cosmic` passes on a machine with
  cosmic-ray 8.7.0, including the live survivor test.
- [ ] A run with any errored or unrun mutant, or a failing baseline, is reported unfinished.
- [ ] The production command's mutant workers run the repository's tests with pytest available.

### Verification

```bash
python3 -m pytest plugins/saga/tests/test_review_adapters_python.py -k cosmic
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
claude plugin validate --strict plugins/saga
git diff --check
```

### Risk

medium

The adapter feeds the testing lens, which the corpus calibration measures; a wrong fix either hides surviving mutants
or floods findings.

### Notes / conventions

Part of #147; blocks saga-review-corpus#3's first full run. Do not bump the saga version. Never download packages in a
test; a live test that needs a package not available offline skips with a stated reason.
