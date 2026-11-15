---
title: saga: scan a whole repository with the review catalogue's security tools
repo: infiquetra-agent-plugins
type: capability
team: asgard
project: agent-platform
stage: Shaping
status: Discovering
labels: capability, needs-plan
risk: medium
handoff_maturity: requirements-ready
approval_state: approved
---

# saga: scan a whole repository with the review catalogue's security tools

### Objective

Give an operator, or any agent that can run a shell command, one command that runs the security rows of saga's
review tool catalogue over a whole repository at one commit and writes the results outside that repository.

### Intent

The runner in `plugins/saga/scripts/review_tools.py` reports only what a change introduces. It takes a base commit
and a head commit, and `filter_to_change` drops every tool hit that falls outside the changed lines. That is right
for code review. It leaves a gap for an audit: a dependency with a known advisory, a secret already in history, or
an infrastructure or workflow misconfiguration that predates the change under review is never reported.

The catalogue in `plugins/saga/references/review-tools.yaml` already holds eleven working security rows:
semgrep-security, gitleaks, osv-scanner, bandit, pip-audit, cdk-nag, checkov-cdk, checkov-cfn, zizmor, npm-audit and
cargo-deny. Each has a pinned version and the flags that keep it offline or metric-free where the tool allows it. A
whole-repository scan should reuse those rows, so there is one list of tool invocations and it cannot drift from a
second one.

The scan is deterministic and needs no model, so it behaves the same under every agent and on every machine. It is
meant to run beside a reasoning audit, not inside one. The public skill `cloudflare/security-audit-skill`, for
example, uses no scanner at all, and Cloudflare's own write-up reports that agents given Semgrep as a tool did not
call it. The two answer different questions and stay separate.

### Out-of-scope / non-goals

- Changing what code review reports, or how `review_tools.run` filters hits for a review.
- Adding tools to the catalogue (Trivy, TruffleHog, a Swift dependency audit). A security row added later is picked
  up by the scan without further work here.
- Copying or packaging any third-party audit skill in this catalog.
- Passing scan results to reviewers or audit agents automatically.
- Filing findings as issues, or uploading results anywhere.
- Installing a schedule. The command is written to be safe for a scheduler to call; setting one up is separate.
- Scanning uncommitted changes. The scan reads one commit, the repository's HEAD unless another is named.

### Files expected to change

- plugins/saga/scripts/security_scan.py (new entry point)
- plugins/saga/scripts/review_tools.py (only if the runner needs a keyword-only seam; review behaviour unchanged)
- plugins/saga/tests/test_security_scan.py (new)
- plugins/saga/skills/security-scan/SKILL.md (new)
- plugins/saga/references/review-tools.md
- plugins/saga/README.md
- plugins/saga/CHANGELOG.md
- ports/saga.json (the new entrypoint and skill unit)
- docs/engineering-journal/DECISIONS.md

### Tests to add or update

- Selection: only rows whose lens is security run. A fixture row added to the catalogue with that lens is picked up
  with no code change, and a row with another lens is not.
- Whole repository: in a fixture repository, a hit in a file that the latest commit did not touch is reported. This
  is the case the review runner drops.
- Target untouched: after a scan, the scanned repository has no new object, ref, worktree or file. The scan works
  on a disposable copy.
- Output location: an output path inside the scanned repository is refused. A path outside it receives the records
  and a summary.
- Rows that need a synthesized template (cdk-nag, checkov-cdk) are skipped with a stated reason unless the caller
  asks for them.
- A missing tool, a version that differs from its pin, and a missing Semgrep rule cache each appear in the summary
  with the reason, and the exit status tells an incomplete scan apart from a clean one.
- Review unchanged: the existing `test_review_tools.py` cases pass untouched, and one test pins that
  `review_tools.run` output for a fixture change is identical before and after this work.
- The command runs the way a user runs it: `--help` exits 0, and a hermetic end-to-end run with stub tool binaries
  produces the records and the summary.

### Context library links

_none_

### Acceptance criteria

- [ ] One command scans a repository at a named commit, HEAD by default, with every security row that runs on
  source alone, and writes records and a readable summary to a directory outside the repository:
  `python3 -m pytest plugins/saga/tests/test_security_scan.py -k end_to_end` passes, and
  `python3 plugins/saga/scripts/security_scan.py --help` exits 0.
- [ ] A hit in a file the latest commit did not touch is reported:
  `python3 -m pytest plugins/saga/tests/test_security_scan.py -k whole_repository` passes.
- [ ] The scanned repository is unchanged by the scan, with no new object, ref, worktree or file:
  `python3 -m pytest plugins/saga/tests/test_security_scan.py -k target_untouched` passes.
- [ ] An output path inside the scanned repository is refused:
  `python3 -m pytest plugins/saga/tests/test_security_scan.py -k output_location` passes.
- [ ] The summary lists each tool as ran, skipped or degraded with the reason, its version and its hit count by
  level, and names the tools that sent package names and versions to an advisory service:
  `python3 -m pytest plugins/saga/tests/test_security_scan.py -k summary` passes.
- [ ] Rows that need a synthesized template run only when the caller asks for them:
  `python3 -m pytest plugins/saga/tests/test_security_scan.py -k synthesized` passes.
- [ ] The exit status tells a caller apart three outcomes, complete with no findings, findings present, and
  incomplete: `python3 -m pytest plugins/saga/tests/test_security_scan.py -k exit_status` passes.
- [ ] Code review output is unchanged: `python3 -m pytest plugins/saga/tests/test_review_tools.py` passes with no
  existing test edited.
- [ ] A saga skill tells any agent when to run the scan, how to run it and how to read the result, and the
  repository's validation accepts the new skill and entrypoint: `python3 scripts/check_repo.py` exits 0.

### Verification

```bash
python3 -m pytest plugins/saga/tests/test_security_scan.py plugins/saga/tests/test_review_tools.py
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
```

Then run the command against a scratch clone of this repository that holds one planted vulnerable dependency pin
and one planted workflow misconfiguration, both in files the latest commit did not touch. Confirm both are reported
and that the clone is unchanged. The planted files stay in the scratch clone and are never committed.

### Risk

medium

The entry point reuses the runner that every code review depends on. The change is additive and a test pins review
output, but a mistake in the shared runner would reach every review.

### Capability size (human planning hint)

Small for a capability: one entry script, one skill, and their tests, in one package.

### Notes / conventions

Reuse the adapters and the catalogue. Do not add a second list of tool invocations.

The runner's base must be a commit. An orphan commit with an empty tree as the base makes every line count as
changed, which is the whole-repository case, but creating that commit writes objects. Do it in a disposable copy,
never in the scanned repository. Confirm this seam during planning before relying on it.

Results hold vulnerability detail. Never write them inside the scanned repository and never commit them. Keep the
existing rule that a gitleaks record carries the rule, file and line and never the matched text.

Keep the existing pin and degraded reporting. A scan that could not run a row says so; it never reports that row as
clean.

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-11-15-saga-whole-repository-security-scan/capability.md

### Source context
- Source: docs/brainstorms/2026-11-15-saga-whole-repository-security-scan/capability.md
- Source type: brainstorm
- Source title: saga: scan a whole repository with the review catalogue's security tools

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/321
- Number: 321
- Created at: 2026-11-15T17:09:07.942443+00:00
