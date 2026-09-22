# Saga Scenarios

Use scenarios when the user's situation is clearer than the command name.

| ID | Starting statement | Command | Effect | Stop condition | Next route |
|----|--------------------|---------|--------|----------------|------------|
| vague-idea | I have a rough idea but do not know the frame. | `/office-hours` | Names the frame and routes to the next thinking command. | The real problem and key assumptions are nameable. | `/ideate` or `/brainstorm` |
| chosen-idea | We picked this idea; now shape it. | `/brainstorm` | Writes requirements-ready context under `docs/brainstorms/`. | Requirements and acceptance examples are clear. | `/plan` |
| vague-what | Build something like this, but the WHAT is fuzzy. | `/spec` | Writes a precise WHAT spec under `docs/specs/`. | Scope, MVP, non-goals, and failure modes are pinned. | `/plan` |
| plan-review | This plan looks ready; check it before build. | `/doc-review` | Writes readiness findings and applies safe fixes. | No unresolved P0/P1 findings or override is recorded. | `/work` |
| pr-boundary | The branch is built and needs PR readiness. | `/code-review` | Writes a structured code review and gate verdict. | No unresolved P0/P1 findings and review is fresh. | PR via `/work` |
| post-merge-qa | This merged; prove it actually works. | `/qa` | Writes acceptance evidence and a ship verdict. | Verdict is ship or ship-with-deferred. | `/retro` |
| qa-failure | QA failed and we need the right repair path. | `/qa` | Classifies severity and routes by merge state. | Failure is classified as pre-merge repair, post-merge defect, or root-cause investigation. | `/work` or `/investigate` |
| root-cause-investigation | Why is this failing? | `/investigate` | Writes a debug report with causal chain and evidence. | Root cause is explained with no causal gaps. | `/work` or `/brainstorm` |
| strategy-refresh | The repo direction or metrics need updating. | `/strategy` | Updates `STRATEGY.md` through interview and pushback. | Direction, metrics, and tracks are coherent. | `/ideate`, `/brainstorm`, or `/plan` |
| cold-resume | Reconstruct where this work stopped. | `/work` | Re-enters the thread from the run record and the saga ticks it already has. | Next owning command is unambiguous. | `/work` |
| retro-learning | This is finished; capture what we learned. | `/retro` | Records durable learning or proposed lifecycle improvement. | Learning is journaled or a gated improvement proposal exists. | terminal, or `mission-control` when it should become an issue |

## Adjacent Choice Notes

`/office-hours` finds the frame; `/ideate` generates options once a frame is usable.

`/ideate` creates and critiques many candidates; `/brainstorm` deepens one chosen candidate into requirements.

`/brainstorm` explores requirements and approaches; `/spec` interrogates an ambiguous WHAT until it is precise.

`/plan` writes implementation units and decisions; `/doc-review` checks whether that plan is safe to execute.

`/strategy` records direction; `/founder-review` challenges direction, ambition, and scope.

`/work` owns re-entry into an in-flight thread; there is no separate router or resume command after issue 1030.
