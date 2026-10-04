---
date: 2026-10-04
topic: saga-staffing-testing-mods
maturity: requirements-ready
---

# Give infiquetra-agent-plugins its own saga profile, including its functional-test declaration

### Objective

Add a `.saga-profile.json` at this repository's root so saga runs here stop asking the profile
questions, and so this repository declares how its own changes are functionally tested before
review, under the contract issue #97 adds.

### Intent

Issue #97 adds the `functional_test_environment` block and the waiver to the saga profile. Its card
listed this repository's own profile as a file to change, but the survey on 2026-10-04 found that
adding any root profile switches on three live-profile tests in `plugins/saga/tests/`, and those
need the whole profile rather than the new block alone:

- all four profile parameters;
- `main_consumed_directly`;
- `nonproduction_destination` set to `none`;
- a `qa` section.

That is a separate decision about how saga treats this repository, so it moved out of #97.

The likely declaration is `kind: local`, `scope: private`, with the plugin test suite as the test
command. The operator confirms each profile value when this card is planned.

### Risk

low
It adds one configuration file read only by saga runs in this repository, and the live-profile
tests check it.

### Out-of-scope / non-goals

- No change to the profile contract; #97 owns that.

### Files expected to change

- `.saga-profile.json`
- `docs/engineering-journal/DECISIONS.md`

### Tests to add or update

- The three live-profile tests in `plugins/saga/tests/` run, instead of skipping, and pass.

### Context library links

- `plugins/saga/references/repository-profile.md`

### Acceptance criteria

- [ ] `.saga-profile.json` exists at the repository root and declares a functional-test environment or a waiver with a reason.
- [ ] The live-profile tests run and pass.

### Verification

```bash
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 scripts/check_repo.py
git diff --check
```
