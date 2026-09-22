---
name: investigate
description: Find the root cause of a bug, test failure, or error before any fix
argument-hint: "[error | test path | issue# | description of broken behavior]"
---

Load `saga/skills/investigate/SKILL.md`. Run the **systematic-debugging engine**: find
the **ROOT CAUSE** of a bug, test failure, error, or unexpected behavior, then optionally apply a
**gated, trivial-scope, self-verified** fix.

The **IRON LAW**: no fix without root-cause investigation first. The **causal-chain GATE** holds the line
— you do not propose a fix until you can explain the full trigger→symptom chain with **no gaps**
("somehow X leads to Y" is a gap), grounded in **observed** evidence (instrumented boundary values, not
"X seems off"), with a **prediction** for every uncertain link.

`/investigate` is **diagnosis-PRIMARY**: the deliverable is an agent-consumable **DEBUG REPORT**
(`docs/investigations/`). The user chooses fix-vs-diagnosis. Only a trivial / single-concern fix is
applied inline (test-first + the engine's **own** fresh-reproduce verification); real implementation work
routes to `/work` via a `mission-control` issue, design problems to `/brainstorm`, trackable defects to
`mission-control` with the report **linked as evidence** (never passed to the classifier).

It is **READ-ONLY** on the world and the saga (`gh` / `git` / `saga.py restore`/`ticks` only). It does
**NOT** commit, push, open or merge a PR, deploy, file SDLC issues, write the saga, or route to `/qa` to
verify. It is **off-chain** — it does not advance `lifecycle_phase`.

Arguments provided to the command:

`$ARGUMENTS`
