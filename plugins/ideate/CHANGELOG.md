# Changelog

## [0.1.0] - 2026-11-19

### Added

- Initial standalone `ideate` package. Grounded ideation skill with skill-local fail-open `shaping_judgments.py` and its Fleet Core modules.

### Fixed

- Judgment commands resolve `shaping_judgments.py` from the skill directory, not the repository working directory.
- Named-repo and context-library grounding check `~/workspace/infiquetra` clones before a remote read.
- `.ideate/runs/` scratch is gitignored.
