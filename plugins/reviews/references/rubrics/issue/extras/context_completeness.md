---
phases: [issue]
applicability: conditional
---
# Context Completeness lens

Your focus: does the issue body contain enough technical pointers
that an agent can plan WITHOUT guessing? Insufficient context
produces planning loops that hallucinate file paths, reinvent
existing helpers, or skip established conventions.

## When you fire

Picker selects you when the issue describes a code change in a
non-trivial repo where conventions / file layout / shared
abstractions matter (which is most non-trivial repos).

## What to look for

- **Named files / modules.** Does the issue identify the
  files/modules where the change goes, or does it leave the
  agent to grep the codebase from scratch? Specific paths
  ("`lib/services/registration_service.dart`") prevent
  hallucination.
- **Cross-references.** If the change interacts with existing
  code (calling a function, extending a class, conforming to an
  interface), is the existing code's location pointed at?
- **Conventions to follow.** "We pattern <X> after <Y>." For
  any non-obvious convention this code should follow, the
  issue should name a precedent ("see how `Service A` handles
  it").
- **Test expectations.** What test file does the new test go
  in? What test framework? What style (table-driven? property-
  based? snapshot?). Issues that don't specify test expectations
  produce inconsistent test styles across PRs.
- **Data model linkages.** If the change touches data models,
  does the issue point at the model definitions, the migration
  history, the validation rules?
- **API contract linkages.** If the change touches API surface,
  does the issue point at the OpenAPI / proto / typed-client
  definition? Without a pointer, the agent might create new
  types that diverge from existing ones.
- **Permitted vs. forbidden additions.** Some issues need
  explicit "you may add file X but DO NOT touch file Y" —
  particularly when there's a tempting-but-wrong path through
  adjacent code.
- **External docs referenced.** If the change implements a
  third-party API, RFC, or SDK feature, is the spec link in
  the issue? Agents that have to hunt for external docs hit
  rate-limits and lose context.
- **Missing-context proxy.** Even without auditing each item:
  if you imagine yourself as an agent picking up this issue
  with zero prior context, can you start planning, or do you
  need to read 5 files to even know where to start?

## Scoring

- **10**: Files named, cross-references provided, conventions
  cited, test expectations specified, external docs linked.
  Agent could plan without grepping.
- **9**: Strong; one or two pointers thin (e.g. test framework
  not specified).
- **8**: Adequate; the load-bearing pointers are present.
- **7**: Issue describes the WHAT but not the WHERE; agent
  will need to grep significantly.
- **≤6**: Issue is high-level prose with no technical pointers.
  Agent will hallucinate or get lost.

## REVISE criteria

REVISE with: a specific missing pointer + impact. "Issue says
'add a registration endpoint' but doesn't name where. The repo
has registration logic split across 3 services. Add a pointer:
'this lives in services/registration-api/, see existing
endpoints in routes.ts for the pattern to follow.'"

## BLOCK only for

- Issue is so context-thin that planning is impossible. The
  agent would need to do discovery work before planning, which
  is more expensive than the human writing 3 lines of context
  upfront.
