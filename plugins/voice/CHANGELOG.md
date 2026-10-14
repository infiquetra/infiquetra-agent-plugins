# Changelog

All notable changes to the voice package are recorded here from 0.4.1. Earlier
releases are recorded only in the git history.

## [0.4.1] - 2026-10-14

### Changed

- Presentation metadata (author, repository, license, and keywords) now lives in the
  portable `plugin.json`. The Claude manifest keeps `author` and its paths, and no longer
  repeats `repository` or `keywords`.

- The Python floor in `SKILL.md` frontmatter now sits under `metadata`, not as a top-level
  `compatibility` key.

- The Codex manifest, `.codex-plugin/plugin.json`, is generated from the portable
  `plugin.json` (infiquetra-agent-plugins #77).

- The Claude manifest description now names the Auralis bridge adapter, and its keywords add
  `text-to-speech`, `speech-to-text`, and `accessibility` (infiquetra-agent-plugins #62).
