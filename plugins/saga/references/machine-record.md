# The machine record

Setup records facts about the operator's machine in one file under the home directory. The file is
not inside a repository, and it is not under `.claude/saga/runs`. That store is one checkout's run
records. This file is the machine.

```
<home>/.saga/machine.json
```

`--home` replaces the home directory. Tests pass a temporary directory. The command defaults to the
operator's home.

The parent directory is the same one the review runner uses (`review_tools._saga`). When this
script creates it, the directory mode is `0700` and the file mode is `0600`.

## Shape

Schema `machine_record.v1`.

| Field | Holds |
|---|---|
| `schema` | `machine_record.v1` |
| `ran` | true after `survey` has written the file. `record_offer` does not set it. |
| `offered` | true after admission, or the setup pane, has suggested setup. `survey` does not clear it. |
| `survey` | the survey document without its `questions` list. Tool status and version, credential state as present or absent, the sandbox result, and which optional steps are done. Never a credential value. |
| `updated_at` | UTC, second resolution, `Z` suffix. |

`record_survey(home, survey)` sets `ran` and stores the survey. `record_offer(home)` sets `offered`
and keeps `survey` and `ran`. Admission calls `record_offer` when it prints the one suggestion.
Card C14 calls the same function for the mod's first-session offer, and may keep its own store as
well.
