# Claude Code and AGENTS.md: why an import line is needed

Recorded 2026-11-22. This note holds the evidence behind the decision "Root CLAUDE.md is a
one-line import of AGENTS.md; GEMINI.md is retired" in
`docs/engineering-journal/DECISIONS.md`, so that the decision does not cite a temporary file.

## Claim

Claude Code reads a repository's `AGENTS.md` only when no `CLAUDE.md`, `CLAUDE.local.md` or
`.claude/CLAUDE.md` exists in the working directory or in any folder above it. That fallback is
unreliable on a second Claude account whose `CLAUDE_CONFIG_DIR` is relocated away from
`~/.claude`, because `~/.claude/CLAUDE.md` then stops being the user file and counts as a
`.claude/CLAUDE.md` in the ancestor folder `~`. Every session in a folder under the home
folder then has a Claude instruction file above it, and the `AGENTS.md` fallback never fires.

## Evidence

- **Code path.** Claude Code 2.1.330. The `AGENTS.md` fallback is decided by an ancestor
  lookup over the names `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md` (binary byte
  offsets 334902261 and 334889432). The ancestor walk (byte 303061356) climbs from the working
  directory to the filesystem root and skips only automount roots. Its only exclusions are the
  managed file and the user file `<config dir>/CLAUDE.md` (byte 291751561). Nothing refuses a
  file because it sits in a config folder (refusal list at byte 300035626).
- **Live sessions.** Company-account transcripts show the personal `~/.claude/CLAUDE.md`
  injected as a project instruction file, which is the ancestor effect described above. In one
  repository under the home folder, company-account sessions loaded `AGENTS.md` in 0 of 15
  tries. Personal-account sessions in this repository loaded it in 3 of 3.
- **Not reproduced.** The result was not reproduced in a fresh live session. The code path and
  the transcripts agree, which is why the decision relies on an import line that works whatever
  the loading rule turns out to be.

## What the 2026-10-13 probe missed

The probe behind the 2026-10-13 entry ran in throwaway directories, so it could not see an
ancestor folder effect. Its conclusion holds only for the personal account.
