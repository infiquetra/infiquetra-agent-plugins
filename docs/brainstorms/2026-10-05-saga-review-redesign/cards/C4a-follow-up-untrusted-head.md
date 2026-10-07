# saga: the review-tools runner treats the change under review as untrusted

### Objective

Make saga's review-tools runner (`plugins/saga/scripts/review_tools.py`, merged in #186 for #151)
treat the commit under review as untrusted input, so that nothing the reviewed change contains can
switch off, narrow, forge or stale-cache its own scan. Do this before any card calls the runner.

### Intent

A security review of #186, checked against `origin/main` at 85bf82e, found that the runner trusts
the checkout it is reviewing in several places. Nothing calls the runner yet: it is inert until a
later card (C11's build loop, then the single review command) wires it in. But C4b (#152), C4c (#153)
and C5 (#154) add adapters and checks on top of it in wave 3, and would copy each flaw.

What the reviewed change can do today:

1. **Scan the working tree instead of the head commit.** `ScanContext(repo, repo, ...)`
   (`review_tools.py:390`) sends Semgrep, gitleaks and lizard to the working tree, while the diff comes
   from commits (`review_diff.py:54`). Uncommitted edits that remove the flagged lines make the
   scanners see clean files. The changed-line filter then keeps nothing, and the review comes back
   green.
2. **Supply its own coverage.** Coverage files (`coverage.json`, `lcov.info` and the like) are read
   from the repository root (`review_tools.py:1004-1020`). A committed fake `coverage.json` reports a
   coverage of 1.0 and no uncovered lines. `coverage_report` may also be an absolute path or contain
   `../` (`:1011`), which reads outside the repository.
3. **Rewrite its own profile.** The profile is the tracked `.saga-profile.json`
   (`references/repository-profile.md:10`), read from the reviewed checkout (`:668-681`, `:893-904`,
   `:953-969`).
   - One `rules` entry under `pins.semgrep` replaces the pinned security rule pack for both Semgrep
     adapters, and no degraded input is recorded.
   - The profile also names the relocated test command, which runs with the operator's full
     environment (`:918`; only `HOME` is replaced). A command of `true` clears the relocated-run
     check. A hostile command is arbitrary code execution as the operator.
4. **Supply saga's own rules.** `plugins/saga/references/semgrep-rules` is resolved inside the
   reviewed checkout (`:700-702`). In this repository, a change can therefore rewrite the rules that
   review it.
5. **Configure the scanners.** Every scanner runs inside the reviewed checkout, and nothing switches
   off settings found there:
   - Semgrep runs without `--disable-nosem` (`review_adapters_all_languages.py:47-52`), so
     `# nosemgrep` comments and `.semgrepignore` apply.
   - gitleaks runs without `--config` (`:108-111`), so `.gitleaks.toml`, `.gitleaksignore` and inline
     `gitleaks:allow` comments apply.
   - jscpd reads `.jscpd.json`, lizard reads `whitelizard.txt`, and osv-scanner reads
     `osv-scanner.toml` with its ignored-vulnerability list.

   A change that adds a token marked `# gitleaks:allow`, or a `.semgrepignore` covering `src/`, is
   reported with no finding and no degraded input.
6. **Hide behind a stale or forged base cache.**
   - The base-results cache key uses `base` as the caller typed it (`:1269-1271`). `--base main`
     therefore reuses one cache file after main has moved.
   - The cache content is trusted unchecked (`:1288-1307`).
   - A vulnerability fixed on main and reintroduced by the change is still listed in the stale base
     results, so it is dropped as "already present at base" (`:505`). Any process running as the same
     user can also write that file.
7. **Look clean by producing nothing.**
   - Empty output with exit 0 counts as a clean result (`:561`). jscpd writes its JSON report to a
     file, not to standard output, so jscpd may never report anything.
   - Semgrep's `errors` array is discarded (`review_adapters_all_languages.py:67-97`), so a file
     Semgrep skipped, such as one over 1 MB, passes silently.

The principle this card adds to the design: the commit under review is untrusted, and nothing it
contains configures its own review. Settings come from the base commit and the plugin. Where the
change touches review settings, that is recorded for the reviewer to see, and never applied.

### Out-of-scope / non-goals

- New adapters or languages (C4b #152, C4c #153), pattern checks (C5 #154), or wiring the runner into
  the build loop or the review command.
- Changing which tools run, their pinned versions or the outcome table's severities.
- Sandboxing the relocated test run beyond an allow-listed environment. Its network and filesystem
  confinement belongs with the card that wires the runner in.

### Files expected to change

- `plugins/saga/scripts/review_tools.py`
- `plugins/saga/scripts/review_adapters_all_languages.py`
- `plugins/saga/scripts/coverage_lines.py`
- `plugins/saga/references/review-tools.md`
- `plugins/saga/references/repository-profile.md`
- `plugins/saga/tests/test_review_tools.py`
- `plugins/saga/tests/test_review_adapters_all_languages.py`
- `plugins/saga/CHANGELOG.md`
- `docs/engineering-journal/DECISIONS.md`
- `docs/engineering-journal/LEARNINGS.md`

### Tests to add or update

- `test_review_tools.py`:
  - an uncommitted edit that deletes a flagged line in the checkout leaves the head finding in place;
  - a head `.saga-profile.json` that replaces `pins.semgrep` rules or the relocated test command
    changes nothing, and is recorded as a head profile change;
  - a committed `coverage.json` at head is ignored;
  - a `coverage_report` path that is absolute or leaves the repository is refused;
  - the relocated command sees only allow-listed environment variables;
  - saga's Semgrep rules resolve to the plugin's own copy, never the reviewed tree;
  - a base cache written for an older base SHA is not reused;
  - a cache file whose recorded key does not match is ignored and the base is rescanned;
  - empty output with exit 0 is a degraded input.
- `test_review_adapters_all_languages.py`:
  - Semgrep's argv carries `--disable-nosem`, and gitleaks' argv carries the plugin's pinned
    `--config`;
  - `.semgrepignore`, `.gitleaks.toml`, `.gitleaksignore`, `.jscpd.json`, `whitelizard.txt` and
    `osv-scanner.toml` at head are removed from the scanned worktree, and each is recorded as a
    degraded input naming the file;
  - a changed line carrying `gitleaks:allow` is recorded;
  - Semgrep's `errors` entries become degraded inputs.

### Context library links

- `docs/brainstorms/2026-10-05-saga-review-redesign/plan.md` (Change 4, the tool framework)
- `docs/brainstorms/2026-10-05-saga-review-redesign/cards/C4a-tool-framework.md`
- #151, #186

### Acceptance criteria

- [ ] AC-1: every adapter scans a detached worktree at the resolved head SHA, so an uncommitted edit
  in the reviewed checkout changes no finding. Proven by `python3 -m pytest
  plugins/saga/tests/test_review_tools.py -q --import-mode=importlib -k head_worktree`.
- [ ] AC-2: the profile is read from the base commit. A head change to `pins`, rules or the test
  command does not apply, and is recorded as a head profile change. Proven by `-k head_profile`.
- [ ] AC-3: coverage comes only from the relocated run's own output. Any coverage path outside the
  repository is refused. Proven by `-k coverage_source`.
- [ ] AC-4: the relocated test command runs with an allow-listed environment. Proven by `-k
  relocated_environment`.
- [ ] AC-5: scanner settings in the reviewed tree do not apply. Each settings file found at head is a
  degraded input naming the file. Semgrep runs with `--disable-nosem`, and gitleaks with the plugin's
  pinned config. Proven by `python3 -m pytest plugins/saga/tests/test_review_adapters_all_languages.py
  -q --import-mode=importlib -k scanner_settings`.
- [ ] AC-6: saga's Semgrep rules always come from the plugin, never the reviewed tree. Proven by `-k
  saga_rules_source`.
- [ ] AC-7: the base cache is keyed on the base commit SHA, the adapter, its pinned version and its
  settings. A stale or mismatched cache is ignored and the base rescanned. Proven by `-k base_cache`.
- [ ] AC-8: empty output with exit 0, and every Semgrep `errors` entry, are degraded inputs, not clean
  results. Proven by `-k empty_or_errored`.
- [ ] AC-9: `review-tools.md` states the untrusted-head rule, and `DECISIONS.md` records it. The saga
  suite passes: `python3 -m pytest plugins/saga/tests -q --import-mode=importlib`.

### Verification

```bash
python3 -m pytest plugins/saga/tests/test_review_tools.py plugins/saga/tests/test_review_adapters_all_languages.py -q --import-mode=importlib
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
```

### Inputs inventory

- The reviewed repository's working tree, head commit and base commit.
- `.saga-profile.json` at base and at head.
- Scanner settings files at head: `.semgrepignore`, `.gitleaks.toml`, `.gitleaksignore`,
  `.jscpd.json`, `whitelizard.txt`, `osv-scanner.toml`.
- Coverage reports.
- The base-results cache under the user's home directory.
- The operator's environment, as passed to the relocated command.

### Failure modes / pre-mortem

- Scanning a head worktree but resolving one path against the original checkout leaves a hole.
  Guard: one test per adapter showing an uncommitted edit has no effect.
- Removing settings files also removes ones a repository legitimately needs, so the first real run
  floods with findings. That is the intended behaviour, and the degraded inputs name each file so the
  base profile can carry what is needed.
- A forged cache still passes if its key is reproducible. Guard: rescan on any mismatch, and prove
  that a moved base is never served.

### Stop conditions

- If a fix would require running a scanner with network access or a changed pinned version, stop and
  report.
- If the base commit has no profile, and reading it from base would break C3's (#150) setup flow,
  stop and report rather than falling back to the head profile.

### Risk

high

Review integrity: the runner decides which findings exist, and today the change under review can
silence or forge them.
