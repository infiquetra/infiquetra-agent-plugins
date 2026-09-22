# Changelog

## [0.1.1] - 2026-09-22

0.1.1 — imported from infiquetra-claude-plugins@acc99fe7 (upstream 0.1.0); authored here from this commit; no provenance manifest from now on.

### Changed

- The output style moved from `output-styles/` at the package root to `com.infiquetra.claude/output-styles/house-style.md`. Claude Code's plugins reference names the default directory `output-styles/` and the manifest key `outputStyles`, and that key replaces the default scan rather than adding to it (https://code.claude.com/docs/en/plugins-reference, read 2026-09-22). This catalog forbids `output-styles/` at a package root, because another harness would read it as portable core. The root Claude manifest therefore sets `outputStyles` to `./com.infiquetra.claude/output-styles/`. Upstream omitted the key because the style sat at the default location, which this layout cannot keep.
- The patch version moved from upstream 0.1.0 to 0.1.1 to mark the authored cut. The portable manifest, the root Claude manifest, the adapter manifest, and the marketplace entry all state 0.1.1. There is no MCP server, so there is no `serverInfo.version` to keep in step.
- The portable `plugin.json` description now says the package is Claude-only and that the portable runtime is empty. The two reference documents stayed at `references/`, which is where the importer classifies them: they are text other packages copy, not a Claude runtime surface.
- The adapter manifest kept every upstream field except the version. `relocate-claude-manifest` preserves those bytes, and the marketplace reads `repository` from the root Claude manifest, which already names this repository.

### Tests

No upstream test was dropped.

`tests/test_house_style_contract.py` was carried from the upstream repo-wide suite and rewritten where its premise was the upstream layout. Two assertions changed: the style file is required under `com.infiquetra.claude/output-styles/` and forbidden at the package root and under `.claude-plugin/`, and the root Claude manifest is required to declare `outputStyles` pointing at that directory. The frontmatter, placard, tell, keyword, and coherence assertions are unchanged. The upstream mutation checks still prove those checkers go red when the contracted text is removed.

`tools/output_style_scorer.py` and `tests/test_output_style_scorer.py` were not carried. The repo-wide triage marks that pair as a maintainer transcript tool, not a contract of this package, and this package ships no code for it to score from.

### Unchanged

The style file, the subagent presentation preamble, and the Claude instructions annotation are the upstream bytes. Nothing in them was rewritten to make a test pass. The package reaches no Fleet Core module, so it declares no `fleet-bundle.json`. It has no command and no script, so no skill was authored over one.

## [0.1.0] - 2026-08-08

### Added

Initial release (issue #704). This ships the whole plugin at once — the plan built it across several
units, but nothing prior to this shipped, so there is no earlier version to diff against.

- `output-styles/house-style.md`, an output style governing the SHAPE of a main-thread turn: which
  turns are full orientations and which are deltas, the three-line closing block whose last line is a
  decision answerable with "go", when a visual is required and when it is forbidden, and how a
  subagent's return is relayed. It also carries two mechanical enforcement tests — bare identifiers
  and abbreviations — that sit beside the language rules in `~/.claude/CLAUDE.md` without rewriting
  them. Word-level rules such as leading with the answer stay in `~/.claude/CLAUDE.md` and in the
  subagent preamble below; the style does not restate them. `keep-coding-instructions: true` is set literally; `force-for-plugin`
  is not set, so the operator's own style selection is never overridden. A "Placard" section states
  plainly what the style suppresses. A single-line tell, `::house-style::`, is emitted on the main
  thread only (never by subagents) as a machine-checkable marker that the style is active on a given
  transcript.
- `references/subagent-presentation-preamble.md`, the canonical presentation-contract text, authored
  once and consumed twice: copied verbatim into 36 plugin agent definition files (Lever A, the reach
  path this plan calls the agent-definition route) and read by saga's workflow emitter to stamp the
  same text onto every emitted `agent()` prompt (Lever B, the emitter-funnel route). The two levers are
  two delivery paths for one piece of text, not two different texts.
- `references/claude-md-annotation.md`, recording why the seven Plain English rules stay in
  `~/.claude/CLAUDE.md` rather than moving into this style: `CLAUDE.md` reaches every subagent a
  session spawns, while an output style reaches only the main thread.
- `plugin.json` manifest and `README.md`. No `outputStyles` key is set — the default `output-styles/`
  location is auto-discovered by Claude Code and that key exists only to override it.

### Not in this release

- Route (c), the main-thread stamp that would additionally cover the largest block of subagent output
  written directly by the main thread rather than relayed from a subagent — deferred to follow-up work
  by the plan's KTD5 (a Key Technical Decision, a recorded design choice with its rejected
  alternatives), not cancelled.
- Target values for the success criteria. The requirements document carries directions ("up,
  substantially") and no numbers; picking them is deferred to planning and is not invented here.
- Any measured effect of this release. The preamble governs no subagent until the plugin cache is
  updated AND a new session starts, so an "after" measurement taken before that reads the old
  behaviour. `README.md` states the four-step chain.

### Note on the closing-ceremony size threshold

The style ships a provisional threshold — roughly six lines — set by feel rather than by measurement,
because requirement R9 asks for one and a state-change test alone never exempts a short turn that did
work. It is expected to move after first contact.
