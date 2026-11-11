# Changelog

All notable changes to the voice package are recorded here from 0.4.1. Earlier
releases are recorded only in the git history.

## [0.5.0] - 2026-11-10

Voice moves from old Herdr (`herdr agent`, `herdr pane`, `~/.config/herdr`) to herdr
core (`hc`) and the Herdr app. Old Herdr is retired, and sessions started in herdr core
were unreachable from 0.4.1.

### Changed

- `voice bind <terminal>` binds a herdr core terminal, named or addressed (`t7`), with
  `hc get --json`. It refuses a terminal on another machine, a finished one, and one
  without the `voice.agent-session` label. `binding.json` stores the terminal address in
  place of the pane id, so **a binding from 0.4.1 reads as unreadable: run `voice bind`
  again**.

- Delivery types the transcript into the bound terminal with `hc keys`, one key per
  character and never Enter, after reading its status with `hc get`. It never uses
  `hc send`, which presses Enter. A blocked agent still gets nothing, and the transcript
  is still held.

- `hc keys` can type only letters, digits, spaces and `` . , ' - ; / = ` [ ] `` exactly
  (herdr core 0.1.20). **A transcript with any other character, including every
  question mark, is held and never typed**, and so is one starting with `/`. The
  refusal is spoken; `d` discards it. Spoken questions cannot be delivered until herdr
  core can paste text without Enter. A failed `hc keys` call also holds the transcript.

- The Auralis bridge identity comes from herdr core: `HC_TERMINAL_ID`, `hc get`, and the
  terminal's `voice.agent-session` label. The terminal address is both `terminal_id` and
  `pane_id`. It is resolved only while Auralis has published its bridge discovery file,
  so without Auralis no hook or presence loop runs `hc`.

- The settings `HERDR_PANE_ID` and `HERDR_BIN_PATH` are replaced by `HC_TERMINAL_ID` (set
  by herdr core) and `VOICE_HC_BIN` (default `hc`).

- Preflight checks the stop key in the Herdr app's `~/.config/herdr-app/keys.json`
  instead of old Herdr's `config.toml`, following a key's mod command to the mod's
  `exec("voice", ["stop"])` call. It reports under `herdr-app-keys`.

### Added

- A SessionStart hook in the Claude adapter labels its own terminal with the Claude
  session id (`voice.agent-session`) on every start, resume, clear and compact. Restart
  each Claude session once after updating so the label exists before binding.

- `tests/conftest.py` hides `hc` and `HC_TERMINAL_ID` from the suite, so tests run inside
  a Herdr terminal cannot reach the real herdr core.

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
