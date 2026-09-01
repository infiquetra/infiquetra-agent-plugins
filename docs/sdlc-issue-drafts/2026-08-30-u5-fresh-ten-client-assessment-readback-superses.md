---
title: U5 — Fresh ten-client assessment, readback, supersession, and fingerprint bindings
repo: infiquetra-agent-plugins
type: capability
team: asgard
project: operations
stage: Shaping
status: Discovering
labels: capability, needs-plan
risk: high
handoff_maturity: requirements-ready
approval_state: approved
---

# U5 — Fresh ten-client assessment, readback, supersession, and fingerprint bindings

### Objective

Re-establish the observational evidence that says what the resynchronized package
is, and bind it so that a future resynchronization can never leave that evidence
stale in silence.

Operator ruling 3: explicitly supersede the old ten-client compatibility matrix and
post-activation readback, bind both replacements to the resynchronized package
fingerprint, and require a fresh ten-client assessment and readback before release
and closeout.

### Intent

**Why the old evidence is retired, mechanically.**
`scripts/check_compatibility_matrix.py` recomputes a package's file count and tree
digest from disk on every run and refuses a mismatch. The committed matrix records
64 files and tree `651ac28a…`; the resynchronized package holds 71 files and a
different digest. The recorded decision "A re-synchronization does not renumber the
evidence it invalidates" forbids editing those numbers: the matrix says so in its
own text, and forty observed stage results and ten client readbacks would become
claims about bytes nobody ran.

**The supersession order is enforced by code, not just policy.**
`check_document_status()` requires a superseded document to name a `superseded-by`
successor that exists and is **itself current**, plus a `superseded-reason`. A
further guard refuses a superseded stamp while the document's fingerprint still
identifies the package in the current revision. So the stamp cannot be written
early: the resync must land, the new assessment must run, the successor must be
published as current, and only then may the old document be marked superseded.

**The readback binding is new work, and it closes a real hole.** No test in this
repository binds either mission-control evidence document. `tests/test_check_compatibility_matrix.py`
binds UniFi only — `PACKAGE_ROOT = ROOT / "plugins" / "unifi"` and
`REAL_CONFIG = port_config.load("unifi", ROOT)`. The mission-control readback is
not even discovered as a matrix document: its record uses `release` and `readbacks`
keys rather than `package` and `clients`, so pointing the checker at it reports
"$.package: missing or not an object, so nothing binds the record to a tree". Under
ruling 3 both replacements get bindings, so the next resynchronization surfaces the
retirement instead of hiding it.

**Add the bindings in the test file, never in the script.**
`scripts/check_compatibility_matrix.py` is one of the five files in the cycle-16
mutation proof's graded set; editing it retires that proof and forces a separate,
expensive re-run. The binding pattern already lives in
`tests/test_check_compatibility_matrix.py`, which is not graded. Add parallel
mission-control classes rather than parameterizing the existing UniFi ones —
parameterizing puts UniFi's live bindings at risk for no gain.

**The two packages' readbacks are not the same shape.** Mission Control's record
carries `schema_version`, `captured_on`, `release`, `method`, `readbacks`, and
`cycle_16_verification`. It has no `profile_states` block — that is a UniFi concept
tied to `site_profile.py` — and it records three readback clients, not ten. The
mission-control binding asserts the `release` block and every `readbacks` entry, and
omits the profile-state assertions. Decide explicitly whether the replacement keeps
a `cycle_16_verification` equivalent.

**The assessment is operator-attended and cannot be unattended.** It needs the real
binaries for the Grok and Agy launchers supplied by `--real-binary`, because the
harness never infers them: `which` returns the wrapper, and a wrapper pointed at
itself spawns descendants until the host gives out. Cursor must run against the real
authenticated home, or an isolated home strips its authentication and records a
false failure. Hermes runs in an isolated home only. Coverage is mandatory; passing
is not — no failing client blocks this work, and no client-specific remediation may
begin without a separate operator decision.

### Out-of-scope / non-goals

- No edit to `scripts/check_compatibility_matrix.py`, `scripts/assess_clients.py`, or any other mutation-proof graded file.
- No renumbering of the superseded documents. They keep the fingerprints they actually ran against.
- No client-specific remediation, adapter, or distribution work.
- No change to anything under `plugins/mission-control/`. The fingerprint is frozen before this unit begins.
- No new blocking gate wired into continuous integration without a separate decision.

### Inputs inventory

- The frozen package after U3: 71 files, new tree digest, pin `3b2b7083`, version 2.15.2.
- `docs/evidence/2026-08-25-mission-control-compatibility-matrix.md` — currently `matrix-status: current`, binding 64 files and tree `651ac28a…`.
- `docs/evidence/2026-08-25-mission-control-post-activation-readback.md` — historical, currently bound by nothing.
- `scripts/assess_clients.py` — the ten-client roster and every recorded client quirk.
- `tests/test_check_compatibility_matrix.py` — the binding pattern to mirror.
- Operator-supplied: real binaries for Grok and Agy, and the real authenticated home for Cursor.
- Floor interpreter with the package's third-party imports: `pytest`, `pyyaml`, `requests`, `urllib3`.

### Files expected to change

- `docs/evidence/2026-08-25-mission-control-compatibility-matrix.md`
- `docs/evidence/2026-08-25-mission-control-post-activation-readback.md`
- `docs/evidence/` — one new compatibility matrix and one new post-activation readback
- `tests/test_check_compatibility_matrix.py`
- `docs/engineering-journal/DECISIONS.md`
- `docs/engineering-journal/QUEUED.md`

### Tests to add or update

- A mission-control matrix-binding class in `tests/test_check_compatibility_matrix.py`, asserting the recorded fingerprint, name, and version against the live package.
- A mission-control readback-binding class asserting the `release` block, the per-skill-unit fingerprints for all seven skills, `upstream_commit` and `version` against `PROVENANCE.json`, and every `readbacks` entry.
- A test that the two superseded documents each carry a `superseded-by` naming a current successor and a `superseded-reason`.

### Failure modes / pre-mortem

**Most likely: the numbers get edited instead of re-measured.** It is one line to
update a digest and it turns forty observed stage results into fiction. The matrix's
own text names this: "Refreshing the numbers without re-running the assessment is
precisely the failure this binding exists to catch."

**Second: the supersession stamp is written before a current successor exists.** The
checker refuses, but a run that treats the refusal as a tooling problem rather than
an ordering error will look for a way around it. There is no way around it that is
honest.

**Third: the binding is added to the graded script instead of the test file**,
retiring the cycle-16 mutation proof for no reason.

**Fourth: a byte changes inside the package after the assessment runs**, silently
invalidating the record. Confirm the tree digest before and after the run and record
both.

**Fifth: a client is recorded as failed for a harness reason.** This has happened —
Cursor was once recorded failed because an empty scratch home stripped its
authentication. A blocked row with the requirement named is the honest record; a
failure attributed to the package is not.

### Stop conditions

| Condition | Action |
|---|---|
| The package tree digest differs before and after an assessment run | Discard that run's record. It describes bytes that no longer exist. |
| A supersession stamp is refused by the checker | Stop. Fix the ordering, never the guard. |
| Editing an evidence number would clear a failure | Stop. Re-run the assessment or leave it red. |
| A binding would require editing `scripts/check_compatibility_matrix.py` or another graded file | Stop and escalate. |
| A client's real binary cannot be supplied | Record that client `blocked` with the requirement named. Never infer the binary, never skip the client. |
| Any verification harness found unsound | Discard that round's evidence and re-run. A harness that cannot fail proves nothing. |
| Any live GitHub write from the assessment | Run-level stop. |

### Context library links

- `docs/runbooks/portable-plugin-port.md` — Phase 3 and the client-assessment quirk table
- `docs/engineering-journal/DECISIONS.md` — "A re-synchronization does not renumber the evidence it invalidates"
- `docs/engineering-journal/LEARNINGS.md` — "A digest in an evidence record proves nothing until something recomputes it"

### Acceptance criteria

- [ ] The package fingerprint is captured before and after the assessment and is identical, recorded from `python3 scripts/check_compatibility_matrix.py --print-fingerprint mission-control`.
- [ ] A fresh ten-client assessment ran against the frozen package, covering all ten clients across placement, discovery, load, and invocation.
- [ ] The new compatibility matrix validates: `python3 scripts/check_compatibility_matrix.py docs/evidence/<new-matrix>.md` prints `Compatibility matrix validation passed.`
- [ ] The new post-activation readback records the release block, all seven per-skill fingerprints, and every client readback.
- [ ] The old matrix carries `matrix-status: superseded`, a `superseded-by` naming the new matrix, and a `superseded-reason`, and `python3 scripts/check_compatibility_matrix.py docs/evidence/2026-08-25-mission-control-compatibility-matrix.md` passes on that basis.
- [ ] The old readback is likewise marked superseded with a named successor and reason.
- [ ] New binding tests fail if either replacement's recorded fingerprint stops matching the package, proven by a deliberate local mutation that makes them red and is then reverted.
- [ ] `python3 -m unittest discover -s tests` reports `OK`.
- [ ] Neither `scripts/check_compatibility_matrix.py` nor any other graded file changed, proven by `git diff --name-only <base>..HEAD -- scripts/ | wc -l` printing `0`.

### Verification

```bash
# Fingerprint the frozen package, before and after the run
python3 scripts/check_compatibility_matrix.py --print-fingerprint mission-control

# Print the assessment plan; runs nothing
python3 scripts/assess_clients.py --package mission-control

# Execute the ten-client assessment (operator-attended; real binaries supplied)
python3 scripts/assess_clients.py --package mission-control --execute \
  --python <venv>/bin/python3.12 --workspace <scratch> \
  --real-binary grok=<path> --real-binary agy=<path> --out <record>.json

# Validate the new evidence and the supersession chain
python3 scripts/check_compatibility_matrix.py docs/evidence/<new-matrix>.md
python3 scripts/check_compatibility_matrix.py docs/evidence/2026-08-25-mission-control-compatibility-matrix.md

# Bindings and gates
python3 -m unittest tests.test_check_compatibility_matrix -v
python3 -m unittest discover -s tests
git diff --name-only <base>..HEAD -- scripts/ | wc -l
```

### Handoff maturity
requirements-ready

### Suggested next action
Use `/plan <issue>` to create an implementation plan.

### Source context
- Source: session issue-shaping pass, 2026-08-30, validated against a fresh upstream fetch
- Source type: operator-settled shaping decisions
- Source title: Mission Control resynchronization 2.12.2 to 2.15.2 — settled shaping

### Recommended Tier Band
opus/high

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/56
- Number: 56
- Created at: 2026-08-30T19:24:38.428517+00:00

