# Changelog

## [0.1.0] - 2026-11-19

### Added

- Initial standalone `brainstorm` package. Requirements-shaping skill with an inlined slugify helper and skill-local fail-open judgments.

### Fixed

- Judgment commands resolve `shaping_judgments.py` from the skill directory, not the repository working directory.
- `.brainstorm/scratch/` is gitignored.
