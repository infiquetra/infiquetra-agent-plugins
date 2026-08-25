# Saga Code Review — U6 test custody, CI wiring, entrypoint generalization (`u6-tests-agy1`)

This review covers the frozen G3 commit on `orch/mcport-9-resume1-u6-tests-agy1` because the floor-pinned plugin-tests job and the generalized entrypoint check are the enforcement that makes the ported suite real, and an exit-status-5 mask would again let a declaring package collect nothing and still go green.

## Outcome

- Typed Saga review result contract (`review_result.v1`): `accepted`
- Next action: `continue`
- Reviewed revision: `c3e5808f190f2e984daf07afa0fa1c6787dc28e4` (`c3e5808`, `feat(ci): enforce the ported mission-control test surface (run unit U6)`)
- Named base: `efc6daf5b585fa721c9c9d96b42ef50b1b81d24c`
- Target: 5 files, +344 / −103
- Review backend: `inline`
- Active findings: none
- Cycle: 1 of 3; no repairs requested

> **Verdict: revision `c3e5808` is accepted.** CI no longer masks empty collection; entrypoints iterate `ports/*.json`; the package suite is 266 passed with no repo-root conftest; cycle-15 binding is intact. CHANGELOG is correctly omitted from floor declaration sites. `test_prompt_alignment.py` is the U1/U3 dropped-from-source disposition, not part of the 266.

## Scope and built-versus-planned audit

**Scope Check: CLEAN** (`tests/test_check_repo.py` and the journal are in-scope consequences: the cycle-15 survivor kill was routed onto this card, and the card required a placement decision in the journal.)

- Intent (child #16 / plan U6 / Key Technical Decision 4): wire `plugin-tests` to `plugins/*/tests` with PyYAML and no exit-status-5 mask; generalize `tests/test_client_entrypoints.py` across every descriptor; add mission-control floor declaration sites; prove conftest independence; do not edit upstream test content.
- Delivered: that, plus the missing-source killing test and a CI glob meta-check.

### Plan-completion (U6)

| Item | State | Evidence |
| --- | --- | --- |
| CI `plugin-tests` uses `plugins/*/tests` glob + `pyyaml` | DONE | `.github/workflows/ci.yml`; pin remains 3.12 |
| Exit-status-5 mask removed | DONE | judgment (a) |
| Entrypoints iterate `port_config.load_all` / `assessment.entrypoints` | DONE | judgment (c); 5/5 tests pass; control deletes `_bundled/` |
| Credential prefixes stripped per package | DONE | `GH_`/`GITHUB_` and `UNIFI_` from each descriptor |
| Hermetic skip-not-fail for missing third-party imports | DONE | `skipTest` inside `subTest` continues the loop (probed with yaml blocked) |
| Floor sites include mission-control README | DONE | `DECLARATION_SITES`; README states `python>=3.12` |
| Floor sites include mission-control CHANGELOG | CHANGED | journaled exclusion; byte-copy has no floor specifier (judgment below) |
| Package pytest green, no repo-root conftest | DONE | 266 passed in 1.41s; no `conftest.py` at repo root |
| Cycle-15 graded files untouched | DONE | all five footer digests match |
| Killing test for missing data-file source | DONE | `test_missing_data_file_source_is_reported_as_stale_source` |
| Journal placement/custody record | DONE | DECISIONS.md 2026-08-24 U6 entry |

COMPLETION: 10/11 DONE, 1 CHANGED (CHANGELOG site, recorded).

## Judgments

### (a) Exit-status-5 mask is gone

Parent `plugin-tests` ran `python -m pytest tests -q`, captured `$?`, and treated status 5 as success. Frozen job is `python -m pytest plugins/*/tests -q` with no wrapper. Pytest exit 5 (empty collection) fails the job. PyYAML is on the install line. The hermetic `unittest discover` job is unchanged.

KTD4's "empty collection for a declaring package" is enforced at job scope: a glob that matches nothing is red. A second package with an empty `tests/` directory beside a non-empty one still yields a non-empty collection — that is the glob-not-per-package trade KTD4 accepted over path enumeration.

**Satisfied.**

### (b) Meta-check exists

`tests/test_check_repo.py` `ContinuousIntegrationTests`:

- Asserts `pytest plugins/*/tests` is in `ci.yml`, and that `plugins/*/tests` directories exist on disk.
- Control: `fnmatch` of two path strings against `plugins/*/tests`, then a broken pattern that does not match `plugins/unifi/tests`.

The card allowed "only if not already implied." The glob *is* the on-disk pattern, so disagreement requires changing the invocation string, which the first test fails. Plan F6 said add a separate checker only if the glob was insufficient; they added one anyway.

Residual: the first test does not zip each on-disk dir against the glob (it only asserts the list is non-empty), and the control hardcodes `plugins/unifi/tests`, which is not on disk. Not a silent-green of the CI job. **Exists. Not missing.**

### (c) Iteration, not enumeration; control can fail

`port_config.load_all` → `available()` = sorted stems of `ports/*.json`. Entrypoint tests drive `config.assessment.entrypoints` (five mission-control scripts, two UniFi clients), not a hardcoded package name. Bundle tests filter `custody.entrypoint_rules` with `startswith("resolve-bundled-fleet-module")`, which matches UniFi v1 and mission-control `-split`/`-guarded`.

`test_removing_the_generated_bundle_breaks_every_entrypoint` copies each package, deletes every `_bundled/` directory, and asserts non-zero plus `ModuleNotFoundError`. `test_the_intact_copy_still_answers_help` is the contrast. Both passed at this revision.

`skipTest` inside `subTest` skips that case and continues the loop (this interpreter: a skip on `"a"` still executed `"b"` and `"c"`). With `yaml` blocked, both `EntrypointTests` still passed — UniFi and the non-yaml mission-control scripts still ran.

**Satisfied.**

### (d) `test_prompt_alignment.py` is the recorded drop, not part of the 266

`python3 -m pytest plugins/mission-control/tests` collected **266 tests and not this file**. Twenty `test_*.py` files sit on disk: the twenty-one upstream tests minus `tests/test_prompt_alignment.py`.

Custody was finalized in U1 (descriptor `dropped_from_source`) and U3 (provenance `removed_from_source`), with a journal entry that the premises fail under the portable layout (relocated Claude manifest, missing catalog-root marketplace and saga skill, superseded README). Plan U6 says if the premise failure first surfaces here, stop and return through the custody owner — it did not first surface here. U6 did not edit the byte-copied tests.

**Recorded custody disposition, not included in 266/266.**

### CHANGELOG vs README on `DECLARATION_SITES`

The card and plan name both files. The diff adds only `plugins/mission-control/README.md`. `CHANGELOG.md` exists as `upstream-byte-copy` (sha256 `c2c988af…`) and contains no `python>=` specifier. `test_every_declaration_site_states_the_floor` would fail if the byte copy were listed. Editing it to add a specifier would break the provenance digest — the journal's rejected alternative. Fleet Core's CHANGELOG is target-owned and can carry the specifier; this one cannot.

**Correct under the floor test's own contract. Not a repair.**

## Lens scores

The canonical lens roster accepts a lens only when its mean applicable-dimension score (`derived_overall`) is at least 9.0 and every applicable dimension is at least 7.0.

| Lens | Derived overall | Accepted | Failing dimensions with scores |
|---|---:|---|---|
| `architecture-maintainability` | 10.00 | `true` | none |
| `correctness` | 10.00 | `true` | none |
| `security` | 10.00 | `true` | none |
| `testing` | 9.80 | `true` | none |
| `documentation-clarity` | 10.00 | `true` | none |
| `adversarial` | 10.00 | `true` | none |

Testing is 9.80 because the CI meta-check's control enumerates path strings rather than pairing each on-disk directory to the glob.

## What was verified

Worktree at `c3e5808`:

- Five graded-file sha256 values equal the cycle-15 footer
- `python3 scripts/check_repo.py` — "Repository validation passed."
- `python3 -m unittest discover -s tests` — 699 ran, 0 failed, 1 skipped (699 = cycle-15's 696 plus the three new tests)
- `python3 -m pytest plugins/mission-control/tests -q` — 266 passed; collection does not include `test_prompt_alignment.py`
- No repo-root `conftest.py`
- `git diff --check` clean; UniFi porcelain empty
- Floor tests 13/13; killing test and CI meta-check 3/3; entrypoint tests 5/5

## Coverage

- Suppressed findings: 0.
- Residual risks, not findings:
  - CI meta-check does not iterate on-disk dirs into `fnmatch`; control names `plugins/unifi/tests`, which is absent. The glob in `ci.yml` is still the load-bearing check.
  - `BUNDLED_OR_INTERNAL_MODULES` is a closed name set; a new internal module not on it could be skipped as "third-party." Current surface is listed.
- Independent gates actually run at `c3e5808`: `check_repo`, discover, package pytest, graded-file digest match, no root conftest, `git diff --check`. `evaluate_review_readiness` `can_proceed` is true.

## Findings

None.

## Routing

`accepted` — continue. No fix requests. The CHANGELOG omission is a recorded custody decision. `test_prompt_alignment.py` remains the U1/U3 drop.
