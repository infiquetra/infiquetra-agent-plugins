# House style

Claude-only package. The portable core is empty of runtime behaviour by design:
this package ships no scripts, no skills, and no executable entrypoint. What it
ships is one Claude Code output style, plus two reference documents that other
packages copy as text.

The style governs the shape of a Claude Code turn: which turns are full
orientations and which are deltas, the three-line closing block, when a visual
is required, and how a subagent's return is relayed. It sets
`keep-coding-instructions: true`, so those rules layer on top of Claude Code's
normal coding behaviour. It does not set `force-for-plugin`, so it never
overrides a style the operator already selected.

The style emits the literal string `::house-style::` on the first line of every
closing block on the main thread. Searching a transcript for that string answers
whether the style was active. Subagents do not emit it. An output style reaches
the main thread only; the preamble below is how the same presentation rules
reach a spawned agent.

## What is in the package

| Path | What it is |
|---|---|
| [`plugin.json`](plugin.json) | Agent Plugins manifest. States that this package is Claude-only and that the portable runtime is empty |
| [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) | Claude Code packaging manifest. Paths only. Declares `outputStyles` into the adapter |
| [`references/subagent-presentation-preamble.md`](references/subagent-presentation-preamble.md) | Canonical presentation text. Other packages copy it into agent definitions and into prompts they emit |
| [`references/claude-md-annotation.md`](references/claude-md-annotation.md) | Why the word-level rules stay in the operator's Claude instructions file: that file reaches every subagent, and an output style does not |
| [`com.infiquetra.claude/output-styles/house-style.md`](com.infiquetra.claude/output-styles/house-style.md) | The output style Claude Code loads |
| [`com.infiquetra.claude/plugin.json`](com.infiquetra.claude/plugin.json) | Relocated upstream manifest. Identity only; it does not redeclare `outputStyles` |
| [`tests/`](tests/) | Contract tests for the style file and the manifest declaration |
| [`CHANGELOG.md`](CHANGELOG.md) | Upstream 0.1.0 history, then the authored cut at 0.1.1 |

## Why the style is not at `output-styles/`

Claude Code discovers a plugin output style in `output-styles/` at the plugin
root. The plugins reference
([component paths](https://code.claude.com/docs/en/plugins-reference)) says the
manifest key `outputStyles` replaces that default directory rather than adding
to it. This catalog does not leave `output-styles/` at a package root, because
a harness that is not Claude Code would read that directory as portable core.
The style therefore lives at `com.infiquetra.claude/output-styles/`, and the
root Claude manifest sets:

```json
"outputStyles": "./com.infiquetra.claude/output-styles/"
```

Without that key Claude scans the empty default directory and the style never
loads. The adapter's own `plugin.json` does not repeat the key: Claude reads
the manifest at the installed package root, and a second declaration would be a
path resolved against the wrong directory.

## How a harness reaches it

**Claude Code.** This repository is a Claude marketplace. From a checkout:

```bash
claude plugin marketplace add /path/to/infiquetra-agent-plugins
claude plugin install house-style@infiquetra-agent-plugins
```

Claude installs the package root, which is what carries both the manifest and
the adapter. Then select the style:

```text
/output-style house-style
```

The same choice is in `/config` under Output style. Selection is the operator's.
The style does not set `force-for-plugin`.

Claude reads output styles when the session starts. Editing the style on disk,
or installing a newer version of this package, changes nothing in a session
that is already running. The same is true of any agent definition that copied
the preamble: Claude reads those once, at session start. After a marketplace
update, start a new session (or run `/reload-plugins` for the style file
itself) before treating a transcript as a measurement of this version.

**OpenCode, Gemini CLI, Muse, and Hermes.** These harnesses reach a package
through its skills. This package has no skill, because it has no script for a
skill to run. What they have is the two files under `references/`, which they
read as documents. Selecting the output style is a Claude Code action.

**Every other harness.** The reference documents are the portable text. The
output style is a Claude Code instruction set, loaded through the manifest key
above. This package ships no command, hook, agent, or MCP server for another
harness to call.

## The reference documents

`references/subagent-presentation-preamble.md` is the canonical presentation
contract, authored once. Other packages copy it verbatim into agent definitions
and stamp it onto prompts they emit. The two delivery paths carry one text.

`references/claude-md-annotation.md` records why the word-level rules stay in
the operator's Claude instructions file rather than moving into the style. The
style deliberately does not restate those rules, except for one mechanical test
it says is a test beside the rule.

Neither document is loaded by Claude as an output style. They stay at
`references/` because other packages copy the preamble from that package-root
path.
