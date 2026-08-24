Before anything else, state on one line your live model id and your reasoning effort, read back from this running session rather than from a config file. If either is not gpt-5.6-sol at xhigh, stop and say so instead of reviewing.

Then run the official Saga Code Review on this worktree: $saga:code-review

TARGET. The diff of this worktree against origin/main. Run `git fetch origin main --quiet` first, then diff against `$(git merge-base origin/main HEAD)`. This is PR #6 of infiquetra/infiquetra-agent-plugins, frozen at f8a6ad81d64f5d14c1825cd6b0e1078e266be776.

LENS SELECTION IS FIXED BY THE OPERATOR, NOT BY YOUR JUDGMENT. Run exactly these seven roster lenses and no others:
  previous-comments, correctness, testing, reliability, adversarial, security, api-contract
Do NOT run architecture-maintainability, privacy, documentation-clarity, agent-usability, performance, deployment-infrastructure, or accessibility-human-usability for this round. api-contract is included because the descriptor contract tightened: `assessment.entrypoints` now requires each declared path to exist in the package, so a descriptor that validated before this change is now refused. The `ports/` and `schemas/` files themselves are byte-unchanged. If you conclude that makes api-contract inapplicable, score it as such and say so rather than substituting a different lens.

Report the complete per-lens score table in your output: for every lens, its derived_overall, its accepted flag, and its failing dimensions with their scores. Report it even when a lens passes.

WHAT THIS ROUND IS. You reviewed revision 00badee059f5c3c6370ccfd98a432936e472d73a of this branch and returned repairs_requested with seven findings, one of them a P0. All seven were repaired in one batch, and the regression and mutation corpus was widened to cover the defect classes rather than the seven instances. This review is of the repaired candidate. Two jobs, in this order:

1. Verify each of the seven repairs actually holds, by probing the behaviour rather than reading the diff for intent. They are:
   - P0, "Copied launcher wrappers are mistaken for real clients": inference was removed outright. `resolve_real_binary` in scripts/assess_clients.py takes the real path only from `--real-binary NAME=PATH` or from the wrapper's own documented override already exported in the environment, refuses a path that is not an executable file, refuses a path that is the same file as the launcher on PATH, and blocks the client naming the requirement when neither source supplies a value. It never searches PATH for a candidate. A copied wrapper, a symlinked wrapper, and an override naming the launcher itself are all covered by tests.
   - P1, "A timed-out descendant survives after its session leader exits": `terminate_process_group` signals the child's own pid, which `start_new_session=True` guarantees is the group id, instead of calling `os.getpgid` on a leader that may already have exited.
   - P1, "A reused workspace silently reuses a mutated package copy": `allocate_run_directory` claims a fresh numbered `run-NNN` inside `--workspace` with `exist_ok=False`, and each client's package copy into it is unconditional.
   - P1, "A nonexistent declared entrypoint is graded as a package failure": both `scripts/check_repo.py` and the harness refuse a declared `assessment.entrypoints` path the package does not carry.
   - P1, "Failure paths discard the transcript needed to finish the record": the transcript is carried through the deadline path, including the timed-out command's partial output, and through the mutated-copy refusal.
   - P2, "The raw transcript is not private in an operator-supplied workspace": the transcript is created through `os.open` with mode 0o600 and re-tightened on overwrite.
   - P3, "Version 2 safety validation inspects the first command twice": a version-2 stage is graded from `commands` alone; version-1 records are still graded from `command`.

2. Review the repaired code on its own terms and look for what both of us have missed. Three changes in this round were NOT requested by you and deserve independent scrutiny; all three are places where the coordinator changed its own mind mid-round, which is exactly where a fresh reader is most useful:

   a. `terminate_process_group` now reaps the direct child before probing whether the process group still holds a member, and the earlier EPERM special-case is gone. The history matters: the first form probed before reaping, saw the child's own unreaped zombie, and reported "a client descendant may survive" on every timed-out stage. A repair read the macOS EPERM as "nothing left to signal", which produced a correct sentence from wrong reasoning and left Linux reporting the warning on every run -- CI caught that. The current claim is that reaping first makes an empty group answer ProcessLookupError on both platforms. Test that claim, including what the code now reports when a descendant genuinely does survive, and whether `process.wait(timeout=2)` can hang or mask a failure.

   b. The mutation proof runner was found to be measuring its own bookkeeping. Every mutation edits a file that `MutationProofBindingTest` hashes, so every mutation failed that test regardless of whether it broke a guard, and the runner counted any failing suite as a kill. Cycle 11's "38 mutations, 0 survivors" therefore established nothing. The runner now excludes that test from grading entirely. Re-graded, seven cycle-11 anchors had no test behind them, and sixteen tests were added. Read the cycle-12 proof header and judge whether the exclusion is sound, whether the sixteen new tests actually constrain the guards they name, and whether any *other* test in this suite can pass for a reason unrelated to what it claims.

   c. Three of those seven guards turned out to be genuinely redundant rather than untested: the transcript's 0600 creation mode (a later chmod leaves the same final mode), the "safety field must be stated" check (a downstream emptiness check refuses the same descriptor), and the mutated-copy status conditional (invalidation already rewrites every stage to blocked, and propose_status over all-blocked already returns "unsupported"). For the first two the new tests pin what the guard uniquely contributes -- the creation-time mode with chmod neutralized, and the diagnostic wording. For the third the anchor was retired as unkillable and replaced by one naming the rewrite. Judge whether that accounting is honest, or whether it dresses up dead code as defence in depth.

REGRESSION CONSTRAINTS, to verify rather than assume:
- plugins/unifi/ must be byte-for-byte unchanged and still fingerprint to 22bfa56828fc7d0fb2246f190730082905bd71b82dee3e8d6e5afc4072498d37 over 23 files
- `python3 scripts/check_repo.py` passes
- `python3 -m unittest discover -s tests` passes (605 tests on the 3.12 floor; both CI jobs are green on this exact revision)
- `python3 scripts/check_compatibility_matrix.py` validates all nine committed version-1 records
- `python3 scripts/sync_vendor_source.py --package unifi --source <a local infiquetra-claude-plugins checkout> --commit 818fd6843e51a9126752061a834db9dead28f72b --check` reproduces the shipped PROVENANCE.json
- docs/evidence/2026-08-23-cycle11-mutation-proof-portable-copies.txt is unchanged from its committed form; the cycle-12 file supersedes it

DO NOT run `scripts/assess_clients.py --execute`. The live ten-client assessment installs software into client directories and is separately gated by the operator. The plan-only form (no --execute) is safe and is the intended way to inspect it.

CONSTRAINTS. Use the inline backend. Do not launch subagents, workflows, or a second reviewer, and do not request an external second opinion -- the engine preference is stored as 'none'. Do not modify any reviewed source: this is a gate, not a fixer.

OUTPUT. Write the complete typed review_result.v1 JSON, exactly as ReviewResult.to_json() emits it, to .review/review-result.json in this worktree. Write the human-readable review artifact beside it at .review/review.md. Do not commit anything; leave both as files.

Never stop to ask a question in this tab: for any choice from a known set, take the most defensible option and say which you took; for a real question about the work, write it into your output and finish, so the coordinator can bring it to the operator.
