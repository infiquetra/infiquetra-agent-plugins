---
name: security-review
description: Audit one committed repository tree for security issues, keeping scanner output separate from reasoned findings. Use when someone asks for a security review, a security scan, a vulnerability sweep, or a trust-boundary review. Suggest code-review for a diff or pull request, doc-review for a plan, spec, or issue, and review-setup when scanner pins or the Semgrep rule-pack digest are missing.
---

# Security Review

Two sections, kept apart.

## Deterministic Scanner Results

Run the committed-tree scanner. It reads the selected commit through Git, builds a disposable snapshot, and leaves the target untouched.

```bash
python3 plugins/reviews/scripts/security_scan.py \
  --repo <repository> --output <results-directory>
```

Exit `0` means every applicable row finished clean. Exit `1` means every applicable row finished and at least one finding was reported. Exit `2` means an applicable row was incomplete or degraded. Incomplete takes precedence over findings. Do not treat exit `2` as a clean audit.

Read `summary.md` and `summary.json`. Report those rows, findings, unscanned submodules, and gaps under the heading **Deterministic Scanner Results**. Quote the scanner. Do not put hypotheses in that section.

Optional flags: `--commit`, `--profile`, `--include-synthesized cdk-nag`, `--include-synthesized checkov-cdk`, `--timeout`.

## Reasoned Security Findings

After the scanner result is recorded, reason about the same committed tree under the heading **Reasoned Security Findings**. Cover trust boundaries, authentication, authorization, injection, secret handling, and data-flow exposure. Label each item as reasoned. A reasoned item does not change the scanner exit code and does not appear inside Deterministic Scanner Results.

Suggest `code-review` for a change range, `doc-review` for a plan, spec, or issue, and `review-setup` when a pin or the Semgrep rule-pack digest is missing.
