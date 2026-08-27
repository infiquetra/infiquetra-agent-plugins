# Changelog

## [1.0.0] - 2026-08-25

### Added

- **Portable single-session launch contract (#777).** New plugin owns create-via-`agents`,
  verify-via-Herdr, prompt delivery, and owned cleanup. An ordinary session can launch one
  verified agent without starting an Orchestrate run. Orchestrate consumes the same module
  (`skills/agent-launcher/scripts/launcher.py`) and no longer keeps a private copy of the
  launcher seam. Explicit dependency on the canonical `herdr` skill for every interaction
  after the session exists; this plugin does not duplicate it. The Agent Plugins port is
  tracked at infiquetra-agent-plugins#22 and does not gate this release.
