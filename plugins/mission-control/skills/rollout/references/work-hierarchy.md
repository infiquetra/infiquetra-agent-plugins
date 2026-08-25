# Work Hierarchy Reference

Practical reference for the Infiquetra work hierarchy. Sources of truth:
`$INFIQUETRA_SDLC_PATH/docs/process/work-hierarchy.md`,
`$INFIQUETRA_SDLC_PATH/docs/process/sub-issues.md`, and
`$INFIQUETRA_SDLC_PATH/config/sdlc-schema.json`.

## Default Model

```text
Initiative field (when present)
  Objective field + Outcome Scorecard doc
    Capability issue (top-level)
      Executable child issue (optional native sub-issue)
```

Initiative and Objective are project-field grouping and reporting axes. An
Objective is not an issue type or native parent. Capabilities are top-level by
default; native sub-issues represent real decomposition.

On a long-lived initiative board whose contract uses dated proof cards, an
Outcome issue may sit between the Objective field and Capability. Do not add
that tier to ordinary Operations or Asgard work merely to manufacture a parent.

## GitHub Constructs

| Role | Canonical construct | Optional construct |
|---|---|---|
| Initiative | Project field option | Owning strategy/context doc |
| Objective | Project field option + Outcome Scorecard doc | Per-repo Milestone |
| Outcome | Dated proof issue on an explicit initiative board | Native parent of Capabilities |
| Capability | Top-level GitHub Issue carrying Objective | Native parent of executable children |
| Executable child | GitHub Issue / PR-sized card | Cross-repo native sub-issue relationship |

## Parent Rules

- Capability: no parent by default; Outcome only under an explicit
  initiative-board contract.
- Enhancement, Defect, Exploration, Context Update: parent the card when one
  Capability genuinely owns the work; leave it top-level when origin is absent
  or ambiguous.
- Use `flow unlink-sub-issue` to remove an accidental or retired parent layer
  without closing either issue.

## Progress

Track Objective progress by filtering the active board on the `Objective`
field. Track decomposition through Capability sub-issue progress. Use optional
Milestone progress only for repo-level due-date and PR rollup.
