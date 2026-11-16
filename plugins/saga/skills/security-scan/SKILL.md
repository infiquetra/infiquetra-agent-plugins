---
name: security-scan
description: Run the review catalogue's deterministic security tools against one committed repository tree and read local findings. Use for a whole-repository security sweep, including findings outside the latest change; keep it separate from reasoning audits and ordinary code review.
---

# Security scan

Run one committed tree through Saga's existing security adapters and read the findings locally.

From a catalogue checkout, this single command scans a scratch clone's HEAD, prints readable findings, and saves the result outside the scanned repository:

```bash
python3 plugins/saga/scripts/security_scan.py --repo ../scratch-security-scan --output ../security-scan-results/run-001
```

For an installed package, locate `scripts/security_scan.py` relative to the Saga package containing this skill; do not assume a vendor-specific environment variable or edit an installed copy. Python and the runner's existing PyYAML dependency are required; the command uses no model or API credential of its own. Use `--help` to inspect the interface without running a scanner.

## Scope and options

The scan reads HEAD by default, or the commit/tag selected by `--commit`; it excludes dirty files, untracked files and earlier history.

- `--repo <path>` names the repository to read.
- `--output <path>` must resolve outside the scanned repository and its Git storage, including linked-worktree storage. Use a fresh directory for each run; an existing empty directory is accepted, a populated directory is refused.
- `--commit <commit-or-tag>` selects the committed tree.
- `--profile <path>` optionally supplies an operator-owned profile from outside the repository. Its pins/rules take precedence over catalogue defaults; the scanned commit's profile and tool settings do not configure the scan.
- `--include-synthesized cdk-nag` and/or `--include-synthesized checkov-cdk` explicitly permit those rows to execute CDK synthesis. Without named opt-in neither row executes target code. Repeating a name runs that row once.
- `--timeout <positive-seconds>` overrides each row's scan timeout, leaving ordinary review timeouts unchanged.

The command creates an independent disposable Git repository with only an empty base and a snapshot of the selected tree. Tree IDs must match before a tool runs; the target gets no objects, refs, worktrees or files. Gitlinks are preserved as `160000` entries, but their content is never read from target working trees or fetched: every tracked submodule is an unscanned gap and makes the scan incomplete.

pip-audit runs without pip dependency resolution. It audits only packages/versions explicitly listed in fully exact-pinned requirement files; unsupported files are named as degraded, and no option re-enables resolution. The command installs no tools or dependencies and downloads no Semgrep rule pack; an unavailable tool or unusable local rule cache remains visible as a gap.

## Read the result

The terminal and `summary.md` show each finding's level, rule and relative `file:line` when available; no second command is needed to read them.

| File | Use |
|---|---|
| `summary.md` | Read row status, finding locations, caveats and advisory-service disclosure |
| `summary.json` | Read the original selected `commit`, `exit_code`, `rows`, `unscanned_submodules` and `advisory_service_rows` |
| `findings.json` | Consume the existing normalized `review_records.v1` finding list |
| `outcomes.json` | Inspect the existing computed `blocks`, `fix-later` and `note` levels |
| `degraded.json` | Inspect runner failures and unscanned submodule gaps |

Each summary row is `ran`, `skipped` or `degraded`, with reason, observed version, resolved pin and counts by level. `ran` with zero findings is distinct from a row that could not run; intentional synth opt-out and absent input are `skipped`. A resolved `not-recorded` pin is displayed as no pin recorded, and does not degrade the row by itself; a real mismatch or unreadable version makes it incomplete.

| Exit | Meaning |
|---|---|
| 0 | Complete scan, no findings |
| 1 | Complete scan, findings present |
| 2 | Incomplete scan or invalid input; findings may still be present |

Incomplete takes precedence over findings. A missing applicable tool, failed execution/parser, timeout, pin mismatch, unusable rule cache, unsupported requirement file or applicable gap never becomes a clean result. Invalid inputs can be refused before any output is written; inspect the terminal when no summary exists.

## Data and follow-up

Results and scan-owned caches are private local artifacts; do not commit them or automatically send them to reviewers, audit agents, services or issue trackers.

The existing osv-scanner, pip-audit and npm-audit rows can send package names and versions to advisory services; `advisory_service_rows` lists those invoked, and cargo-deny may fetch its advisory database. Existing metric/offline flags remain in force; this is not an offline guarantee for dependency audits. Gitleaks records keep the rule, file and line while matched text is removed before persistence or printing.

Treat this as deterministic scanner evidence beside a reasoning audit. It neither scores the repository's overall security nor changes ordinary review's changed-line/base-head behavior. If a required detection is blocked, report that gap to the operator rather than claiming the repository is clean.
