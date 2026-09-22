# Import mission-control, 2026-09-22

The mission-control package in infiquetra-agent-plugins is now authored here.
The import read infiquetra-claude-plugins at acc99fe7 (upstream plugin version
2.21.0). The authored version is 2.21.1.

## Evidence

- Dry-run of `scripts/import_vendor_package.py --package mission-control --commit acc99fe7` classified `scripts/executor_profile_lint.py` as `resolve-bundled-fleet-module-split` and `scripts/sdlc_manager.py` as `resolve-bundled-fleet-module-guarded`, and dropped `scripts/fleet_commons_shim.py`. That matches the 2.15.2 custody table's shim rules.
- The same dry-run copied `scripts/sync_template_docs.py`, `tests/test_issue_contract_parity.py`, and `tests/test_template_sync.py` unchanged. Those three were `resolve-package-root-marker` transforms in the derived port, because that port had no `.claude-plugin/` directory. The authored layout generates `.claude-plugin/plugin.json` at the package root, which is the marker those files walk for. Rewriting them onto `com.infiquetra.claude/plugin.json` would point the walk at the adapter instead of the package root.
- After the guarded rewrite, `sdlc_manager.py` still imported `fleet_commons_shim` in `_load_saga_readiness_owner` (loads `plugin_resolution`) and in `_fleet_commons` (loads `typesafe_client` and `jev_log` by name). The import script reports a file as unresolved only when no rule matches. A rule that matches one block leaves the other call sites in place. Both sites now import `scripts/_bundled/`.
- `fleet-bundle.json` declares `intent_envelope`, `plugin_resolution`, `tier_palette`, `tier_resolver` (loaded by `intent_envelope`), `typesafe_client`, `retry_backoff` (loaded by `typesafe_client`), `jev_log`, and `staffing.json` (read by `tier_palette` and `tier_resolver`). `models.json` is not declared. Fleet Core 0.32.0 folded that file into `staffing.json`.
- `flow repair-window` adds or removes a label and posts a comment. It is in `assessment.mutating_operations`. The rest of that list is the 2.15.2 audit.
- The 2026-08-30 compatibility matrix and readback are superseded. Their successor is `docs/evidence/2026-09-22-mission-control-compatibility-notice.md`, which records that no ten-client run was performed for 2.21.1. Older mission-control evidence now names that notice directly, because a superseded document's successor has to be current.

## Mechanism

The guarded fleet rewrite matches one contiguous block. Upstream 2.21.0 grew two more shim call sites in the same file after the 2.15.2 pin. A successful rule application is not proof that every shim mention in the file was rewritten. The dry-run note "reaches plugin_resolution, intent_envelope" is the set of string-literal `fleet_commons_shim.load("...")` calls, read before the rewrite. `_fleet_commons(module)` does not match that pattern, so `typesafe_client` and `jev_log` were not declared until the call sites were read by hand. Each of those modules' own sibling loads (`tier_resolver`, `retry_backoff`, `staffing.json`) had to be declared too, or the bundled copy fails when it imports the sibling beside itself.

## Generalizable rule

After `import_vendor_package.py`, search the written tree for `fleet_commons_shim` and for `fleet_commons_shim.load` with a variable argument. The classification table names a file resolved when one rule matched, not when every call site was rewritten.

## Calls

- Carried `tests/test_prompt_alignment.py` and retargeted command and agent paths under `com.infiquetra.claude/`. The derived port dropped it because the package had no root `.claude-plugin/plugin.json` and no marketplace entry. Both exist in this layout.
- Carried `tests/test_card_validator_agreement.py`. It already skips when the home-lab authority file is absent.
- Dropped `test_palette_arrives_via_shim_rung_provenance` from the carried `tests/test_executor_profile_lint.py`. It points `FLEET_COMMONS_ROOT` at a fake fleet-core. The lint imports the bundled palette and does not read that variable.
- `tests/test_saga_readiness_alignment.py` skips cases that load `plugins/saga/scripts/handoff_envelope.py` when that file is absent. Saga is a separate import. The missing-saga diagnostic test still runs.
- Added `plugins/mission-control/tests/conftest.py` with the upstream no-live-gh tripwire. That fixture lived in the upstream repo's `tests/conftest.py`, which does not apply under `plugins/*/tests`. Without it, the carried self-test called the operator's `gh`.
- Added `skills/triage/SKILL.md`. The package had a `/triage` command and no skill.
- Skill documents no longer locate the CLI by walking from `INFIQUETRA_SDLC_PATH` into `infiquetra-claude-plugins`. The script's own default for that variable is unchanged.
- `PACKAGE_ROOT_MARKER_SITE_COUNTS["mission-control"]` stays in `scripts/sync_vendor_source.py`. The transform's tests use that slice as the worked example. The live descriptor is authored and selects no rule. `tests/test_port_config.py` now allows an authored package to remain in the slice.
- The repository root README still describes the derived 2.15.2 package. Twelve import branches share that file, so this unit did not rewrite it. Links that cited the 2026-08-30 matrix as current now say the record is superseded. `tests/test_mission_control_rule_audit.py` pins the package changelog instead of the root README.
- `tests/test_fleet_bundle_schema.py` and `tests/test_bundle_fleet_module.py` asserted the 2.15.2 bundle (`intent_envelope`, `tier_palette`, `models.json`, `staffing.json`). They now assert the modules 2.21.0 loads.
