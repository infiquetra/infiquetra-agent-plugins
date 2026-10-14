<!-- matrix-status: notice -->

# Issue #237 single repair pass

Date: 2026-10-14. Reviewed implementation: `1ccf4ce`.
The controller consolidated 34 lens findings into the 18 repairs below and
explicitly deferred the assessment engine refactor. This records one repair pass;
it does not claim a second code review or live workstation acceptance.

| Finding | Repair and verification |
|---|---|
| CR-237-01 | Muse reports excluded packages as not applicable under `all`; fake-client tests cover planning, check and execution, and the native house-style reproduction passes. |
| CR-237-02 | `--client` is required again; missing selection exits 2, and the default-all documentation is removed. |
| CR-237-03 | Selected records from the previous registration are uninstalled before retargeting; the stateful fake and native two-stage reproduction preserve unselected records. |
| CR-237-04 | Legacy registrations are selected by their repository source and attributed through registry/worktree/available paths; `infiquetra` migrates, while registrations needed by unselected plugins survive. |
| CR-237-05 | Readback receives catalog, home and staging inputs; registration and installed package paths must match the requested stage. Native matching and mismatched checks pass. |
| CR-237-06 | Check names selected standalone skill collisions without deleting directories or symlinks; unselected skills do not fail filtered checks. |
| CR-237-07 | Muse project scope is refused before any state change; marketplace installs omit scope, and the fake CLI rejects that flag. |
| CR-237-08 | Private, owned staging requires a custody marker; only previously listed owned entries may be swept. Foreign entries survive without publication, and symlink/ownership/permission tests cover refusal. |
| CR-237-09 | Muse assessment copies retain symlinks for containment checking and fingerprint the staged package independently; outside links and mutations block the row. |
| CR-237-10 | Otherwise-good inspect records with invalid or missing/null/nonempty diagnostics capture nothing and block invocation. The load-only T237-1 mutant is killed. |
| CR-237-11 | One options object passes through the planning APIs; `plan_install` composes cleanup, `plan_uninstall` never installs, and explicit fatal flags stop dependent actions. Structured readback carries source-failure policy. |
| CR-237-12 | Shared CLI constants, parsers, attribution, availability and retries live in `scripts/muse_cli.py`; assessment no longer imports the installer. Staging paths use the shared default. |
| CR-237-13 | The staging generator accepts `name`; both callers pass it, with no post-generation rewrite or stub catalog. |
| CR-237-14 | Muse action payloads name catalog, scope, package and skill data directly. Generic schema/message/target fields retain their generic meanings. |
| CR-237-15 | `MUSE_CATALOG_MARKETPLACE_ALIAS` names the compatibility alias and documents its source. README and the decision explain its purpose and retirement trigger. |
| CR-237-16 | Explicit client id/name mapping replaces positional pairing; inventory tests refuse marketplace alias or package-exclusion drift. |
| CR-237-17 | Runbook exit rules, scope limitations, retries, migration, staging custody and strict checks match the repaired implementation; the 1.1.0 amendment remains recorded. |
| CR-237-18 | Journal and architecture text use the issue title and 2026-10-14 date; projection has a definition link, learning rules are single sentences, and mutation evidence defines both cycles and carried digests. |

ARCH-4 is recorded in [QUEUED.md](../engineering-journal/QUEUED.md#muse-stage-command-and-observation-hooks-arch-4),
to revisit when another client needs extra commands or JSON observations.

The [native transcript](2026-10-14-issue237-review-repair-checks.txt) covers the
controller's requested reproductions under disposable homes. The refreshed
[Cycle 29 proof](2026-10-13-cycle29-mutation-proof-muse-client-roster.txt) kills
34 mutations and binds the exact bytes of all five graded files. Its filename
follows the October 13 plan date; this repair ran on October 14.

Repository lint now has explicit default correctness rules and a 100-character
formatting width in [ruff.toml](../../ruff.toml), avoiding inherited operator
configuration. Two existing unused test imports were removed so the requested
whole-repository lint command is clean. No plugin versions or maintained
installed copies changed.
