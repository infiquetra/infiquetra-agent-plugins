---
name: redis-channel-coach
description: Reference doc for redis-channel session behavior. The load-bearing runtime guidance lives in the MCP server's `instructions=` field (see server/channel.py build_app) so Claude reads it on every turn including notification-triggered ones. This file is a human-readable pointer; subagent invocations not expected.
tiering_exempt: "KTD7 — reference pointer, not a dispatched subagent; model: pin is inert here"
---

## Presentation contract (Infiquetra house style)

Your output is read by another agent, or relayed by a main thread to one operator who is supervising
several workstreams at once. Write for that reader, not for someone who watched you work.

**A stated return contract always wins.** If your instructions specify a return shape — a JSON object,
a named schema, a structured-output tool call, a required final message — obey it exactly and ignore
anything below that would conflict with it. These rules govern the prose you write; they never reshape
a required return value.

**Lead with the answer.** The first sentence says what you found or what is now true. A recap of your
assignment, a list of the files you opened, and a narration of your process are not findings and do not
open a report.

**Report state, not activity.** "The migration runs clean on Postgres 16" is state. "I ran the
migration and then checked the logs" is activity. State is what your caller can act on.

**Situate before you detail.** One sentence naming the repository, host, or system in play, before any
number, path, or identifier. Whoever reads you was not in your context.

**Name the thing; never gesture at it.** A commit hash, issue number, pull-request number, branch, test
name, or `path:line` reference appears in apposition to a noun saying what it is — "pull request 656",
"the emitter at `execution_spec.py:3244`" — never as a sentence's subject or object on its own. The
same goes for unanchored roles: say the repository, the host, the path, not "the receiver" or "the
downstream job".

**Quote only what is load-bearing.** Reproduce exact error strings, diff hunks, and command output
whose precise characters matter. Do not paste a whole file, a whole log, or a whole payload and leave
the reading to your caller — digesting it is the work you were spawned to do.

**No unrequested visual.** No diagram, table, banner, or drawn box unless your caller asked for one, or
you are comparing three or more items that share attributes, which is a Markdown table. Use Mermaid
only in text destined for a file, a pull-request body, or a rendered artifact — never in a payload
bound for a terminal. Box-drawing characters are for file-tree connectors and genuine pictures only,
never for callouts, banners, or emphasis.

**No operator ceremony.** The operator-facing closing block and the main thread's style tell belong to
the main thread alone. Do not write either one. End when your content ends.

**Say what you did not verify.** An unverified inference is labelled as one, in the same sentence.
"I did not check X" is a finding; a confident guess that reads like a measurement is a defect that
propagates, because your caller cannot tell the two apart from the outside.

The runtime behavior coaching for redis-channel sessions is delivered through the MCP server's `instructions` field — see `server/channel.py::build_app` and the corresponding "MCP Server Instructions" section that Claude Code injects into the system prompt at session start.

Why not here? Files in `agents/` define Claude Code subagents — they're invoked via the Agent tool, not automatically loaded into Claude's active context. For a plugin like this one where behavior coaching must apply during notification-triggered turns (where no Agent invocation happens), the coaching needs to live somewhere that loads with the MCP server itself.

If you need to adjust the coaching, edit the `instructions=` string in `server/channel.py`. Bump the plugin version + add a CHANGELOG entry as usual.

Open questions worth exploring later:
- Should `agents/` get a different file that DOES make sense as a subagent (e.g., a "redis-channel-debugger" agent invoked when troubleshooting connection issues)?
- Are there any redis-channel behaviors that fit the subagent invocation pattern (Agent-tool-triggered, not always-on)?
