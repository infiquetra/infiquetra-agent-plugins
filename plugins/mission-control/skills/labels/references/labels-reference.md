# SDLC Labels Reference

Complete label taxonomy for Infiquetra repositories. Source of truth:
`$INFIQUETRA_SDLC_PATH/config/labels.json`

---

## Issue Type Labels (exactly ONE per issue)

Every issue must have exactly one of these labels.

| Label | Color | Description |
|-------|-------|-------------|
| `capability` | `#0E8A16` (green) | Complete, deployable system functionality (1-4 weeks with AI) |
| `enhancement` | `#A2EEEF` (cyan) | Improvement to existing functionality (2-5 days with AI) |
| `defect` | `#D73A4A` (red) | Production bug requiring fix (hours to 2 days) |
| `exploration` | `#D876E3` (purple) | Research, POC, or architectural investigation (1-3 days) |
| `context-update` | `#0075CA` (blue) | Blueprint repository documentation maintenance |

---

## Status Labels

Applied automatically or manually as issues progress through the workflow.

| Label | Color | Description |
|-------|-------|-------------|
| `needs-plan` | `#FBCA04` (yellow) | Current actionable-template planning label read by Hermes |
| `needs-analysis` | `#FBCA04` (yellow) | Requires context gathering and specification |
| `needs-triage` | `#FBCA04` (yellow) | Needs priority and impact assessment |
| `ready` | `#0E8A16` (green) | Context complete, ready for development |
| `blocked` | `#B60205` (dark red) | Work is blocked by external dependency |

`needs-analysis` and `needs-triage` are legacy fallback labels. Current capability,
enhancement, and defect templates apply `needs-plan`; the older labels may still appear when
`labels auto-label` runs against title-pattern rules from `labels.json`.

---

## Priority Labels (ONE required for Defects)

Required for `defect` issues. Optional for other types.

| Label | Color | SLA | Description |
|-------|-------|-----|-------------|
| `critical` | `#B60205` (dark red) | 4 hours | Critical priority — immediate action required |
| `high-priority` | `#D93F0B` (orange-red) | 1 day | High priority — urgent fix needed |
| `medium-priority` | `#FBCA04` (yellow) | 3 days | Medium priority — fix in next sprint |
| `low-priority` | `#FEF2C0` (pale yellow) | As capacity allows | Low priority |

---

## AI Usage Labels

Add when a PR is created to track AI generation percentage. One per PR.

| Label | Color | Description |
|-------|-------|-------------|
| `ai-generated-high` | `#5319E7` (deep purple) | AI generated 70-100% of the code |
| `ai-generated-medium` | `#7057FF` (purple) | AI generated 30-70% of the code |
| `ai-generated-low` | `#B8AFF2` (light purple) | AI generated < 30% of the code |
| `human-only` | `#E4E4E4` (light gray) | No AI generation used |

---

## Technical Area Labels

One or more may apply. Not mutually exclusive.

| Label | Color | Description |
|-------|-------|-------------|
| `security` | `#D73A4A` (red) | Security-related work requiring extra review |
| `performance` | `#FFA500` (orange) | Performance-critical work |
| `infrastructure` | `#006B75` (teal) | Infrastructure or deployment work |
| `documentation` | `#0075CA` (blue) | Documentation updates |
| `testing` | `#5EBEFF` (light blue) | Testing-related work |
| `refactor` | `#C5DEF5` (pale blue) | Code refactoring with no functionality change |

---

## Size Labels

Add during Analysis phase. One per capability or enhancement.

| Label | Color | Description |
|-------|-------|-------------|
| `size:XS` | `#C2E0C6` (pale green) | 1-2 days effort |
| `size:S` | `#7FBF7F` (light green) | 3-5 days effort |
| `size:M` | `#4CAF50` (green) | 1-2 weeks effort |
| `size:L` | `#2E7D32` (dark green) | 2-4 weeks effort |

---

## Risk Labels

Add during Analysis phase. One per capability.

| Label | Color | Description |
|-------|-------|-------------|
| `risk:low` | `#C2E0C6` (pale green) | Low technical risk |
| `risk:medium` | `#FFA500` (orange) | Medium technical risk |
| `risk:high` | `#D93F0B` (orange-red) | High technical risk |
| `risk:very-high` | `#B60205` (dark red) | Very high technical risk — needs mitigation plan |

---

## Workflow Labels

Flags for specific workflow conditions.

| Label | Color | Description |
|-------|-------|-------------|
| `needs-context` | `#FBCA04` (yellow) | Blueprint context is incomplete or unclear |
| `breaking-change` | `#D73A4A` (red) | Introduces breaking changes to APIs or contracts |
| `tech-debt` | `#795548` (brown) | Technical debt that should be addressed |
| `dependencies` | `#006B75` (teal) | Dependency updates or management |

---

## Convention-Based Labels

These labels follow a naming convention and are created on-demand rather than pre-deployed.

### `initiative:*` and `objective:*`

Legacy convention labels that may appear on older issues. New work should use the
project board's `Initiative` and `Objective` fields directly via `flow set-field`.
The plain `objective` issue-type label is also retired and must not be deployed
or applied to new work.

| Pattern | Color | Example |
|---------|-------|---------|
| `initiative:{name}` | `#0052CC` (blue) | `initiative:olympus-v1` |
| `objective:{name}` | `#0052CC` (blue) | `objective:platform-launch` |

---

## Meta Labels

Organizational and process labels.

| Label | Color | Description |
|-------|-------|-------------|
| `good-first-issue` | `#7057FF` (purple) | Good for newcomers to the team |
| `help-wanted` | `#008672` (green) | Extra attention or expertise needed |
| `duplicate` | `#CFD3D7` (gray) | This issue or PR already exists |
| `wontfix` | `#FFFFFF` (white) | This will not be worked on |
| `invalid` | `#E4E4E4` (light gray) | This doesn't seem right or is not applicable |
| `question` | `#D876E3` (purple) | Further information is requested |
| `epic` | `#3E4B9E` (navy) | Large initiative spanning multiple capabilities |

---

## Auto-Label Rules

Applied by `labels auto-label` command. Rules match patterns in issue title or body.
These are legacy fallback rules, not the current GitHub Issue Form template defaults. For current
template labels, use `../issues/references/templates-reference.md`.

| Rule | Pattern (regex) | Labels Applied |
|------|----------------|----------------|
| `title_contains_capability` | `\[CAPABILITY\]` in title | `capability`, `needs-analysis` |
| `title_contains_enhancement` | `\[ENHANCEMENT\]` in title | `enhancement`, `needs-analysis` |
| `title_contains_defect` | `\[DEFECT\]` in title | `defect`, `needs-triage` |
| `title_contains_exploration` | `\[EXPLORATION\]` in title | `exploration` |
| `title_contains_context` | `\[CONTEXT\]` in title | `context-update`, `documentation` |
| `mentions_security` | `security\|vulnerability\|CVE` in title/body | `security` |
| `mentions_performance` | `performance\|latency\|slow\|timeout` in title/body | `performance` |
| `mentions_breaking` | `breaking change\|breaking\|backwards incompatible` in title/body | `breaking-change` |

---

## Usage Rules Summary

1. **Every issue must have exactly ONE issue type label**: `capability`, `enhancement`,
   `defect`, `exploration`, or `context-update`

2. **Defects must have exactly ONE priority label**: `critical`, `high-priority`,
   `medium-priority`, or `low-priority`

3. **Other issue types**: priority is optional but encouraged for clarity

4. **AI usage labels**: Add when PR is created to track AI generation %. One per PR.

5. **Size labels**: Add during Analysis phase. One per capability/enhancement.

6. **Risk labels**: Add during Analysis phase. One per capability.

7. **Planning/status labels**: current actionable templates apply `needs-plan`; `ready` and
   `blocked` may be managed as issues progress. `needs-analysis` and `needs-triage` are legacy
   fallback labels from older auto-label rules.

8. **Technical area, workflow, and meta labels**: Apply as many as relevant. Not exclusive.

---

## Initiative and Objective Fields

These values are project field options. Legacy labels may exist, but they are not the
canonical source of truth:

- `Initiative` project field - strategic grouping
- `Objective` project field - delivery target or parent objective

Set fields directly:

```bash
python3 sdlc_manager.py flow set-field --project mount-olympus \
  --repo <repo> --number <N> \
  --field Objective --option "platform-launch"
```

When creating a new initiative or objective, add the field option using `fields create-option`.

Example label names:
- `initiative:olympus-v1`
- `initiative:platform-stability`
- `objective:platform-launch`
- `objective:q1-2026-mvp`

---

## Label Deployment Notes

When deploying labels to a new repository:

```bash
python3 sdlc_manager.py labels deploy --repo <repo-name>
```

- Creates labels that don't exist
- Updates color and description on labels that exist with different values
- Does NOT delete labels that exist in the repo but aren't in `labels.json`
- Safe to re-run as many times as needed

When auditing a repository:

```bash
python3 sdlc_manager.py labels audit --repo <repo-name>
```

Output categories:
- **Present**: Labels from `labels.json` that exist in the repo
- **Missing**: Labels from `labels.json` that do NOT exist in the repo
- **Extra**: Labels in the repo that are not in `labels.json` (informational only)
