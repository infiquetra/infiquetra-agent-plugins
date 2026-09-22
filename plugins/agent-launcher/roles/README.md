# Roles library

One reusable prompt per role that the software development lifecycle names, written in the
lifecycle's own vocabulary. A roster helper sends one of these files to a fresh agent session so
the session knows what it is, what it reads, what it returns, and when it stops — without anyone
hand-writing a briefing.

The source of truth is the sibling repository `infiquetra-sdlc`. This directory decides no policy of
its own: no role that repository does not name, no contract it does not define, no scoring
threshold. When this directory and that repository disagree, that repository is right and this
directory is stale.

Read from `infiquetra-sdlc` revision `5efc869f`.

**One thing here is copied rather than referenced, and it is worth naming.** Each prompt lists the
required field names of the contract it posts. Those names are the lifecycle's, transcribed — a
second copy that can drift. It is deliberate: a prompt is the whole briefing a fresh session gets,
and a session that has to file a handoff cannot go and read a schema. The copy is made safe by a
test rather than by discipline: `tests/test_roles_library.py` reads each contract's fields from the
lifecycle's run model and fails when a prompt omits a required one. Everything else the lifecycle
owns — the lens dimensions, the anchors, the strictness ladder, the staffing tiers — is referenced,
never copied, because nothing consuming those is mid-task with no way to look them up.

## What is here, and what is not

These files are prompts. Nothing here spawns a session, orders roles, enforces a gate, or combines
results — that is the roster helper's job and the run chain's job.

They are not Claude Code agent definitions. They carry no `model:` or `effort:` field, because
choosing a role's vendor, model and effort is the staffing component's decision, and a tier written
here would be a second place to change it.

## The contract every prompt follows

Each role prompt is a Markdown file with YAML frontmatter and four required sections. It has to be
self-contained: the whole file is the entire briefing a session that has never seen this run will
get.

Frontmatter keys, all four required:

| Key | Meaning |
|---|---|
| `role` | The readable role name, spelled as the role catalogue at `infiquetra-sdlc` `docs/roles/run-roles.md` spells it — Title Case. The lifecycle disagrees with itself here: its run model spells eight of the fifteen in sentence case (`Initial implementation worker`), its role catalogue in Title Case (`Initial Implementation Worker`). The catalogue is the page a person reads, so these files follow it, and the test compares the two without regard to case |
| `role_id` | The lifecycle's stable identifier for the role |
| `emits` | A YAML **list** of the handoff contract identifiers this role produces. Always a list, never a bare string — the Planner produces two and the Delivery Manager five. The list is empty for a role whose result is aggregated into another role's contract rather than posted as its own; the Lens Reviewer is the only such role, and its prompt says where its result goes |
| `source` | Where the content came from, so a reader can check it |

Required sections, in this order and with these exact headings:

| Heading | Holds |
|---|---|
| `## Role` | What the role is, what it may decide, and what it must never do |
| `## Inputs from the run record` | The named inputs the session is given, and where each comes from |
| `## Output contract` | The handoff comment the role posts, in the lifecycle's shape, naming each contract in `emits` by the name the lifecycle gives it and listing its required fields. One role posts nothing of its own — the Lens Reviewer, the only file with an empty `emits` — and its section says where its result goes instead |
| `### Stop rule` | The condition on which this role stops working and hands off |

`### Stop rule` is a level-three heading inside the output-contract section on purpose: the card that
commissioned this directory checks for that exact string, and a structural test enforces it. Do not
promote it to `## Stop rule`.

The lifecycle's own name for this concept is the field `stop_condition`, a required field of the
`dispatch` contract, meaning the deadline or the condition on which a dispatched role stops. The
heading here and the field there are the same idea under two names.

## The output contract, once

Every role posts its result as a handoff comment on the issue record, in the shape
`infiquetra-sdlc` `docs/process/run-contracts.md` fixes, at revision `5efc869f`. The comment opens with a heading naming the contract:

```markdown
### Handoff: <contract name> (<contract-id>)
```

and then carries one bolded field label per line. Four fields come first on every contract, whatever
else follows:

```markdown
**Revision.** <the commit the work is bound to>
**Artifact.** <path@revision, or a link>
**Assigned.** <the role or person who acts next>
**Next.** <the action they take>
```

Each role prompt then names its own contract's required fields, one per line, in the same bolded
form — the field's identifier, capitalised and spaced, then a full stop:

```markdown
**Work unit.** <the unit this result covers>
**Branch and revision.** <branch@commit>
**Mechanical check results.** <each check and its outcome>
```

So `work_unit` is written `**Work unit.**`, and `unexplained_behaviour` is
`**Unexplained behaviour.**`. The rule is worth stating because without it three sessions produce
three spellings of the same field, and the first thing that tries to read these comments has to
accept all three or reject two.

Nothing parses this convention today. That is a real gap and not a small one: a session can post a
handoff missing a required field and no step notices, because the only check in this repository
reads the *prompts* and asserts they mention each field — it says nothing about what a session
actually emitted. A validator over the posted comment belongs with whatever first consumes these
handoffs.

## Role to file map

Fourteen roles, one file each. The lifecycle names fifteen; the Human Operator is a person, not a
session, and gets no prompt.

Two identifiers are historical and deliberately do not match their readable name — the Architect's
identifier is `orchestrator` and the Delivery Manager's is `controller`, both kept for tooling
stability. The files are named for the readable role so nobody opens `orchestrator.md` expecting an
orchestrator.

| Role | `role_id` | File |
|---|---|---|
| Product | `product` | `product.md` |
| Issue Reviewer | `issue_reviewer` | `issue-reviewer.md` |
| Planner | `planner` | `planner.md` |
| Architect | `orchestrator` | `architect.md` |
| Delivery Manager | `controller` | `delivery-manager.md` |
| Initial Implementation Worker | `implementer` | `implementer.md` |
| Plan Reviewer | `plan_reviewer` | `plan-reviewer.md` |
| Review Controller | `review_controller` | `review-controller.md` |
| Lens Reviewer | `lens_reviewer` | `lens-reviewer.md` |
| Standard Repair Implementer | `standard_repair_implementer` | `standard-repair-implementer.md` |
| Expert Repair Implementer | `expert_repair_implementer` | `expert-repair-implementer.md` |
| Release Worker | `release_worker` | `release-worker.md` |
| Functional Tester | `functional_tester` | `functional-tester.md` |
| Investigator | `investigator` | `investigator.md` |

The Lens Reviewer is one file carrying a shared reviewer half and one section per lens, keyed
`#### <lens-id>` to the lifecycle's lens catalogue.

### Slicing the Lens Reviewer

A consumer sends two pieces, joined by a blank line:

1. **The shared half** — everything from the start of the file up to, but not including, the line
   `# The lenses`.
2. **One lens section** — from the line `#### <lens-id>` up to, but not including, the next line
   matching `^#{1,4} `. That terminator matters: the next line after a section is sometimes another
   `####`, sometimes a `##` grouping heading, and for the last section it is the end of the file.
   Slicing "to the next `####`" pulls in a grouping heading that means nothing to the session.

Everything a session needs is in those two pieces. The `## Always on` and `## Conditional` headings
organise the file for a person and are deliberately not sent; nothing load-bearing lives under them
rather than inside a lens section, which is why the always-on-versus-conditional rule and the
permission to report without scoring sit in the shared half instead.

`index.json` carries the machine-readable form of all of this, so a helper does not have to parse
this table or find these headings by hand.

## How a prompt reports

Every prompt points at the house style rather than repeating it:
`plugins/house-style/references/subagent-presentation-preamble.md`, the single canonical copy in
this repository. The prompts that were migrated into this directory each opened with a
byte-identical forty-line copy of that text, one per agent prompt, which is the drift this
library exists to undo.

## Where the retired prompts went

The archived `team-execution` plugin's 25 agent prompts and its two criteria documents were the source
material. This is the one file in this directory allowed to name them, because the accounting has to
live somewhere; the role prompts themselves never mention that plugin.

| Group | Count | Destination |
|---|---|---|
| Reviewers — security, architecture, devil's advocate, code quality, testing, API, infrastructure, privacy, clarity, AI usefulness | 10 | Lens sections of `lens-reviewer.md` |
| Testers — scenario, smoke, API contract, UI regression, performance, concurrency, event flow, SDK regression | 8 | Named strategies in `functional-tester.md` |
| Scanners — security, dependency, API compatibility, infrastructure cost | 4 | Not roles. They become mechanical baseline checks in the build loop, tracked separately |
| Monitors — GitHub Actions, runtime — and the deploy watcher | 3 | Wait steps in `release-worker.md` |

The two criteria documents follow the same rule. The review criteria already delegated every
dimension, anchor and acceptance rule to a roster file and asserted no policy of its own, so its
substance is now the Lens Reviewer's instruction to read dimensions and anchors from the lifecycle's
catalogue. The validator criteria's gate-status vocabulary was that plugin's own invention and is
deliberately not carried; roles record pass-or-fail evidence in their handoff comment instead.

The `team-execution` plugin was archived by issue #1030; its final changelog entry points here.

## The library's declared inputs

Two data files sit beside the prompts, and both are generated rather than hand-written.

`index.json` is what a consumer reads instead of parsing this README: the role-to-file map, each
role's `emits`, the lens identifiers, and the rule for slicing the Lens Reviewer.

`lifecycle-snapshot.json` is the lifecycle's roles, contracts — each required field with the
lifecycle's one-line definition of it — and lenses at the pinned revision, vendored here. It states
which roles and contracts exist, so it is the library's own declaration of what it is built against
— which is why it lives here rather than under `tests/`. The suite checks the prompts against it
everywhere, including where no lifecycle checkout is reachable, and a separate parity check
compares it to the live lifecycle wherever one is.

Neither file is edited by hand. `lifecycle-snapshot.json` carries a hash of its own contents that
the suite recomputes, so a hand edit is caught.

## Adding a role later

Four things change together, and the tests fail until all four agree:

1. The prompt itself, `roles/<role>.md`, following the contract above.
2. The row in this file's `## Role to file map` table.
3. The entry in `index.json`.
4. `lifecycle-snapshot.json`, if the role is new to the lifecycle rather than newly given a prompt —
   regenerate it from the lifecycle at the pin.

The structural test reads the expected set from the map table and from the snapshot, not from a list
inside the test. A row without a file fails, a file without a row fails, and a prompt whose
`role_id` the lifecycle does not name fails — so no half can drift alone, and a role the lifecycle
has not declared cannot be introduced by adding a file.

## Exemptions this file claims

This README is the one file in the directory that carries no stop-rule heading, and the one file
allowed to name the retired plugin. The structural test states both exemptions once, by filename.

The first exemption needs its check anchored to the start of a line. This file has to quote the
heading it mandates — the table above does, twice — so a plain substring search for the heading
matches this file too, and a search for files *lacking* it comes back empty rather than naming this
one. Anchored to a line start, the search says what it means: every role prompt has the heading, and
this file does not.
