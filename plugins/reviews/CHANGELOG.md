# Changelog

## [0.2.0] - 2026-11-20

### Added

- `scripts/builder_record.py` judges one builder-record file and merges a write onto an issue file under `--store-root`.

## [0.1.0] - 2026-11-19

### Added

- Standalone `reviews` package with `code-review`, `security-review`, `doc-review`, and `review-setup`.
- Review packets are written to `--out` or `.reviews/`. An issue number is optional report metadata.
- Security review keeps deterministic scanner results separate from reasoned findings.
- Document review runs the `idea`, `spec`, and `issue` rubrics without continuing into implementation.
- Review setup records tool status and Semgrep rule-pack digests under `~/.config/infiquetra/reviews/`, and reads `~/.saga/machine.json` when the new file is absent.
