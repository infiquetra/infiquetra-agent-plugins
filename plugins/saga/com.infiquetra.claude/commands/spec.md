---
name: spec
description: Interrogate a vague ask into a precise, backlog-ready WHAT spec
argument-hint: "[vague ask | issue# | rough doc path]"
---

Load `saga/skills/spec/SKILL.md` and run the WHAT-interrogation engine. Interrogate the
request — round by round (five-Why -> scope/MVP lock -> technical categories) — until the WHAT is
precise enough that an unfamiliar implementer could build it, then write a sharp
`docs/specs/<YYYY-MM-DD>-<slug>-spec.md` and route onward.

Treat `$ARGUMENTS` as the seed: a vague ask (free text), an issue ref (`#N` — read it read-only with
`gh issue view`), or a rough upstream doc path (a brainstorm requirements doc, an ideation survivor, or
the root `STRATEGY.md`) used as grounding.

**HARD GATE:** do not produce a spec artifact after message 1 — interrogate first. **Read code first:**
before any technical question, read real evidence and cite `path:line` (non-code escape: greenfield /
non-code). `/spec` **never files an SDLC issue** — `mission-control` owns issue creation; `/spec` produces
the source artifact only and is saga-untouched (off-chain).

`$ARGUMENTS`
