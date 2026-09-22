# Changelog

## [0.1.4] - 2026-08-09

### Fixed

- Allow the producer's bounded 30-second network request to finish before the
  Claude Code adapter exits.
- Convert launch and timeout failures into the existing generic service-unavailable error.

## [0.1.3] - 2026-08-09

### Fixed

- Bind the explanatory diagram's SVG source and PNG render to checked SHA-256
  digests and enforce the renderer receipt in the documentation test.

## [0.1.2] - 2026-08-08

### Documentation

- Add comprehensive usage, architecture, development, portability, and
  troubleshooting guidance for the existing Claude Code profile-evolution
  front door.

## [0.1.1] - 2026-08-02

### Fixed

- Match Hermes reply-message validation: reject whitespace-only messages and accept messages up to 16,384 characters.

## [0.1.0] - 2026-08-01

### Added

- Add the Claude Code request-only surface for Hermes target-sovereign profile evolution.
