# GraphQL Queries Reference

Developer reference for all GraphQL queries used by `sdlc_manager.py`.
All queries are executed via `gh api graphql`.

---

## Query: Get Item Node ID

**Purpose**: Resolve a GitHub issue or PR to its internal GraphQL node ID (required before
adding to a project).

**Constant**: `QUERY_GET_ITEM_NODE_ID`

```graphql
query($org: String!, $repo: String!, $number: Int!) {
  repository(owner: $org, name: $repo) {
    issueOrPullRequest(number: $number) {
      __typename
      ... on Issue { id number title }
      ... on PullRequest { id number title }
    }
  }
}
```

**Variables**: `org`, `repo`, `number`

**Usage**: Called first in `board_add()`. The script reads the single
`issueOrPullRequest` union node. Its `id` field is the content node ID used in
project mutations.

---

## Mutation: Add Item to Project

**Purpose**: Add an issue or PR to a GitHub ProjectV2 board.

**Constant**: `QUERY_ADD_ITEM_TO_PROJECT`

```graphql
mutation($projectId: ID!, $contentId: ID!) {
  addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
    item { id }
  }
}
```

**Variables**: `projectId` (project node ID), `contentId` (issue/PR node ID from above)

**Returns**: The new project item's node ID (used for subsequent field mutations).

---

## Mutation: Archive Item

**Purpose**: Archive a project item, typically after it reaches a terminal workflow status.

**Constant**: `QUERY_ARCHIVE_ITEM`

```graphql
mutation($projectId: ID!, $itemId: ID!) {
  archiveProjectV2Item(input: {projectId: $projectId, itemId: $itemId}) {
    item { id }
  }
}
```

**Variables**: `projectId`, `itemId` (item node ID from project items query)

---

## Mutation: Set Field Value (Single Select)

**Purpose**: Set a single-select field on a project item — used to move items between
columns (Status field) and to sync label fields (Initiative, Objective, etc.).

**Constant**: `QUERY_SET_FIELD_VALUE`

```graphql
mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $projectId
    itemId: $itemId
    fieldId: $fieldId
    value: { singleSelectOptionId: $optionId }
  }) { projectV2Item { id } }
}
```

**Variables**: `projectId`, `itemId`, `fieldId` (field node ID), `optionId` (option node ID)

**Note**: Both `fieldId` and `optionId` must be node IDs, not display names. Discover them
via `QUERY_GET_PROJECT_FIELDS` or `board discover-fields`.

---

## Query: Get Project Items (Paginated)

**Purpose**: Fetch all items on a project board, including their field values, labels,
and content metadata.

**Constant**: `QUERY_GET_PROJECT_ITEMS`

```graphql
query($org: String!, $number: Int!, $cursor: String) {
  organization(login: $org) {
    projectV2(number: $number) {
      id
      title
      items(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          createdAt
          updatedAt
          content {
            ... on Issue {
              number title url state
              labels(first: 20) { nodes { name } }
              repository { name }
              milestone { title dueOn }
            }
            ... on PullRequest {
              number title url state
              labels(first: 20) { nodes { name } }
              repository { name }
            }
          }
          fieldValues(first: 20) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field { ... on ProjectV2SingleSelectField { name id } }
              }
              ... on ProjectV2ItemFieldDateValue {
                date
                field { ... on ProjectV2Field { name id } }
              }
              ... on ProjectV2ItemFieldTextValue {
                text
                field { ... on ProjectV2Field { name id } }
              }
            }
          }
        }
      }
    }
  }
}
```

**Pagination**: Uses cursor-based pagination with `pageInfo.hasNextPage` / `pageInfo.endCursor`.
The `get_project_items()` function loops until all pages are fetched.

**Key field paths**:
- Item status: `fieldValues.nodes[].name` where `field.name == "Status"`
- Item type label: `content.labels.nodes[].name` (look for `capability`, `enhancement`, etc.)
- Repository name: `content.repository.name`
- Item age: derived from `createdAt`

---

## Query: Get Project Fields

**Purpose**: Discover all fields on a project, including single-select field options with
their IDs. Required before setting field values.

**Constant**: `QUERY_GET_PROJECT_FIELDS`

```graphql
query($org: String!, $number: Int!, $cursor: String) {
  organization(login: $org) {
    projectV2(number: $number) {
      id
      title
      fields(first: 30, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          ... on ProjectV2Field {
            id name dataType
          }
          ... on ProjectV2SingleSelectField {
            id name
            options { id name }
          }
          ... on ProjectV2IterationField {
            id name
          }
        }
      }
    }
  }
}
```

**Returns**: All field definitions. For `ProjectV2SingleSelectField`, includes options with
both `id` and `name`. Use the `id` values in `QUERY_SET_FIELD_VALUE`.

---

## Query: Get Item Labels

**Purpose**: Fetch current labels on a specific issue or PR (without fetching the full board).

**Constant**: `QUERY_GET_ITEM_LABELS`

```graphql
# pagination-lint: allow (a single issue/PR never carries >30 labels)
query($org: String!, $repo: String!, $number: Int!) {
  repository(owner: $org, name: $repo) {
    issueOrPullRequest(number: $number) {
      __typename
      ... on Issue { labels(first: 30) { nodes { name } } }
      ... on PullRequest { labels(first: 30) { nodes { name } } }
    }
  }
}
```

**Usage**: Legacy helper for `labels sync-fields`. New field updates should prefer
`flow set-field` with explicit project field values.

---

## Query: Get Issue Timeline Events

**Purpose**: Retrieve field value change events for an issue — used to calculate cycle time,
column dwell time, and flow efficiency metrics.

**Constant**: `QUERY_GET_ISSUE_TIMELINE`

```graphql
query($org: String!, $repo: String!, $number: Int!, $cursor: String) {
  repository(owner: $org, name: $repo) {
    issue(number: $number) {
      title
      createdAt
      closedAt
      timelineItems(first: 100, after: $cursor,
        itemTypes: [PROJECT_V2_ITEM_FIELD_VALUE_EVENT]) {
        pageInfo { hasNextPage endCursor }
        nodes {
          ... on ProjectV2ItemFieldValueEvent {
            createdAt
            previousProjectV2ItemFieldValue {
              ... on ProjectV2ItemFieldSingleSelectValue { name }
            }
            projectV2ItemFieldValue {
              ... on ProjectV2ItemFieldSingleSelectValue { name }
            }
          }
        }
      }
    }
  }
}
```

**Usage**: Called by `metrics column-time` and `metrics cycle-time`. Events represent
Status field changes — `previousProjectV2ItemFieldValue.name` is the old column,
`projectV2ItemFieldValue.name` is the new column.

**Pagination**: Same cursor-based pattern as project items.

---

## Mutation: Replace a Field's Option Set (identity-preserving)

**Purpose**: Replace the option set of a single-select field while preserving every
item value — e.g., renaming lifecycle columns or provisioning new ones.

**Constant**: `QUERY_UPDATE_FIELD_OPTIONS`

**Destructive-by-design warning — read before composing any call.**
`UpdateProjectV2FieldInput.singleSelectOptions` **overwrites the whole option set**;
there is no add-one-option mutation, and empty input is ignored. An option keeps its
identity (and every item value pointing at it) only if its **existing `id` is
resubmitted** — omitting the id on a retained or renamed option mints a new option and
**clears every item value that pointed at the old one**. Never submit a partial list:
omitting a live option from the submission deletes it.

```graphql
mutation($fieldId: ID!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
  updateProjectV2Field(input: {
    fieldId: $fieldId
    singleSelectOptions: $options
  }) {
    projectV2Field {
      ... on ProjectV2SingleSelectField {
        id name
        options { id name color description }
      }
    }
  }
}
```

**Variables**: `fieldId` (from `QUERY_GET_PROJECT_FIELDS`); `options` — the **complete**
desired list, where every retained or renamed option carries its existing `id` and only
genuinely new options omit it. Colours must come from
`ProjectV2SingleSelectFieldOptionColor` (`GRAY BLUE GREEN YELLOW ORANGE RED PINK PURPLE`).

**Usage**: Called **only** through `update_field_single_select_options` in
`sdlc_manager.py` (CLI: `fields set-options --project <p> --field <f> --options-file
<complete-list.json> [--dry-run]`). That helper refuses — before the mutation is sent —
any submission that is not the complete desired set, drops a live option, or omits an
existing id on a retained option. There is intentionally **no** one-option write:
the pattern of submitting a single new option through this input replaces the entire
set with it and clears the field on every card. `fields create-option` performs no
mutation at all — it prints the field's id and current options.

---

## GitHub API Notes

### Authentication
All GraphQL calls go through `gh api graphql`. The `gh` CLI handles auth automatically.
No personal access tokens are required.

### API Endpoint
- GraphQL: `https://api.github.com/graphql`
- REST: `https://api.github.com`

### Pagination Pattern
All list queries use cursor-based pagination:
```python
cursor = None
while True:
    data = _graphql(QUERY, {"cursor": cursor, ...})
    items = data["..."]["nodes"]
    page_info = data["..."]["pageInfo"]
    if not page_info["hasNextPage"]:
        break
    cursor = page_info["endCursor"]
```

### Field ID vs. Option ID
- `fieldId`: the node ID of the field itself (e.g., the "Status" field)
- `optionId`: the node ID of a specific option within that field (e.g., "Assigned")
- Both are opaque strings — discover them via `QUERY_GET_PROJECT_FIELDS` or
  `board discover-fields`

### ProjectV2 vs. Classic Projects
These queries use the `ProjectV2` API (GitHub Projects v2). Classic Projects use a different
REST API and are not supported by this script.

### Error Handling
GraphQL errors are returned in `data["errors"]` even with HTTP 200. The `_graphql()` wrapper
raises a `RuntimeError` if the `errors` key is present.
