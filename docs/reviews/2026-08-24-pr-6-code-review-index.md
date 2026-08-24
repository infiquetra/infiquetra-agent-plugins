# PR #6 independent code reviews — provenance index

PR #6 ("Make the porting tools package-agnostic and script the ten-client
assessment") went through five independent Saga code review rounds before it was
accepted and merged as `49918aac11a73810d28be43b3bd3ecbf23d36479`. Every reviewer
was OpenAI Codex `gpt-5.6-sol` at extra-high reasoning, running against a frozen
revision in a detached worktree.

Each round produced three files, preserved here byte-for-byte as they were
written. Scores and findings are **not** edited: a review artifact records what a
reviewer said about one revision, and a later round agreeing or disagreeing does
not change that.

- `...-brief.md` — what the reviewer was told, including the operator-fixed lens
  selection. Kept because it is the only proof that lenses were assigned rather
  than reviewer-chosen.
- `...-result.json` — the typed `review_result.v1` outcome.
- `...*.md` (no suffix) — the human-readable review.

## Rounds

| Round | Reviewed revision | Outcome | Findings | Lenses | Files |
| --- | --- | --- | --- | --- | --- |
| 1 | `9ef88e8a545d988c38d883e099309f3cb64ca628` | repairs_requested | 10 | 11 | not duplicated here — see below |
| 2 | `00badee059f5c3c6370ccfd98a432936e472d73a` | repairs_requested | 7 | 11 | `2026-08-23-pr-6-code-review-round-2-00badee0-brief.md`, `2026-08-23-pr-6-code-review-round-2-00badee0-result.json`, `2026-08-23-pr-6-code-review-round-2-00badee0.md` |
| 3 | `f8a6ad81d64f5d14c1825cd6b0e1078e266be776` | repairs_requested | 3 | 7 | `2026-08-23-pr-6-code-review-round-3-f8a6ad81-brief.md`, `2026-08-23-pr-6-code-review-round-3-f8a6ad81-result.json`, `2026-08-23-pr-6-code-review-round-3-f8a6ad81.md` |
| 4 | `5f2d75aa71c424bc5d8890bcef40c824d1b2834f` | repairs_requested | 4 | 7 | `2026-08-23-pr-6-code-review-round-4-5f2d75aa-brief.md`, `2026-08-23-pr-6-code-review-round-4-5f2d75aa-result.json`, `2026-08-23-pr-6-code-review-round-4-5f2d75aa.md` |
| 5 | `df67a2df2d43e3728030c0c9d7c5813a06139c6b` | accepted | 5 | 7 | `2026-08-24-pr-6-code-review-round-5-df67a2df-brief.md`, `2026-08-24-pr-6-code-review-round-5-df67a2df-result.json`, `2026-08-24-pr-6-code-review-round-5-df67a2df.md` |

Round 5 accepted the branch: all seven lenses passed with no failing dimension.
Four of its five findings are marked `resolved` (they are the round-4 findings,
re-verified); the fifth is an accepted, disclosed P3 recorded in
[the cycle-14 mutation proof](../evidence/2026-08-24-cycle14-mutation-proof-portable-copies.txt).

## Round 1

Round 1's artifacts are already durable on the preserved branch
`orch/orch-pr6-codex-review-codereview-codex` at `dd035c9`, as
`docs/code-reviews/2026-08-23-pr-6-code-review.md` (13971 bytes, blob
`66a4cc8becb131d3144efcb4f7da1f0450a3c3ef`) and `.orchestrate/review-result.json`
(40030 bytes, blob `998320001554cb9511579b61e74a6d1f288e284f`). They are not copied
here: duplicating an artifact that already has a durable home creates two things to
keep in agreement. That branch is preserved for exactly this reason.

Note the directory difference. Round 1 was written by the Saga skill to
`docs/code-reviews/`, which has never existed on `main`. The durable location in
this repository is `docs/reviews/`, which `docs/README.md` documents and which
already holds the pilot's code reviews, so rounds 2-5 land there.

## Integrity

SHA-256 of each file as written by its reviewer and as committed here:

```
fe1c649d94ce0d2d20b30fb0cadc8c5ef377b9b7f5f9fb2c5380908433db4c60  2026-08-23-pr-6-code-review-round-2-00badee0-brief.md
6b89d07ad7ea1db0a83723c5da89c2c4b11dd6d4ed4d703ab3f333a8f780a5bb  2026-08-23-pr-6-code-review-round-2-00badee0-result.json
f330695afb3e55cb5c7a8addf60825b1d89a6db82b38f7fa49ce83688cb102ad  2026-08-23-pr-6-code-review-round-2-00badee0.md
17c94d3c7c48044051231242ba2cabc884ce8bb9379329bf019f7327eacdfba8  2026-08-23-pr-6-code-review-round-3-f8a6ad81-brief.md
8974b680457c8accda06d043a191768c336e23d326d4921624faf976977256e8  2026-08-23-pr-6-code-review-round-3-f8a6ad81-result.json
2f18cbddb325534766c58233230fe223893485d6ca5cb79581200653c58f5bd9  2026-08-23-pr-6-code-review-round-3-f8a6ad81.md
c9c5c1281d9dbfc928aa2f0690914798a9dc34e9eea97d0fa802c8d19e81476a  2026-08-23-pr-6-code-review-round-4-5f2d75aa-brief.md
b02b3f7819736f294155abe977129e771a5ad64d13b4f4a7f8823cfe8a76b60a  2026-08-23-pr-6-code-review-round-4-5f2d75aa-result.json
ef7029d93dd4230319b5015e5dcc4d1904bfaaabe31209e6748c2874bac8a881  2026-08-23-pr-6-code-review-round-4-5f2d75aa.md
130b85a1e96dcaa81bd3b3e2f16309132e6abe96705a2dbb8b2b9284e31cebfd  2026-08-24-pr-6-code-review-round-5-df67a2df-brief.md
0b42706997b7a791146c0b9521ba7ec1056fee25ae74806a2edb58b0bee9b4dd  2026-08-24-pr-6-code-review-round-5-df67a2df-result.json
afe3fd88ad8bdccdc15066add0808162574ba1a4386d6889098bf7d8f998624c  2026-08-24-pr-6-code-review-round-5-df67a2df.md
```

Each round's files came from a detached worktree named `pr6-review-<round>`, held
at the reviewed revision. Those worktrees were removed once these files were
merged and read back.
