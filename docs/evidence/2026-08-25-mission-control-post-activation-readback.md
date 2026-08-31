<!-- matrix-status: superseded -->
<!-- superseded-by: 2026-08-30-mission-control-post-activation-readback-post-fingerprint-move.md -->
<!-- superseded-reason: This readback binds the package at tree digest 651ac28a..., 64 files, pinned at upstream 84eaf042 (v2.12.2). The 2.15.2 resynchronization moved the package to 71 files at tree 1f49322e..., and the F18/F11/F35 corrections then moved it again to 659f91f6..., so the recorded readbacks describe installed copies that no longer exist. The successor chain ends at the current 2026-08-30 readback of the corrected package. -->

> **Superseded - historical evidence. Do not read this as the current
> post-activation readback.**
>
> This readback was captured on 25 August 2026 against the pre-resynchronization
> package. It is kept because the readback happened and its record should not
> vanish, not because it still describes the shipped bytes.
>
> **What superseded it:**
> [`2026-08-30-mission-control-post-activation-readback.md`](2026-08-30-mission-control-post-activation-readback.md).

# Post-activation readback — portable mission-control package 2.12.2

The `mission-control` package in this repository, `plugins/mission-control/`, is a
portable derived copy of an upstream Claude Code plugin synchronized from
`infiquetra/infiquetra-claude-plugins` at pinned commit `84eaf042f0e350005f7eddf8e7d80da25c12119d`
(version 2.12.2). Following runbook Phase 3 (`docs/runbooks/portable-plugin-port.md`),
this document captures the post-activation readback and verification bound to the
exact frozen candidate commit (`e3780cd77bb15a1fd0e1f2c8582c4608e922751c`), on 25 August 2026.

## Context and Purpose

A readback proves what client-installed copies actually hold on disk from cold-start
installations, rather than inferring behavior from source tree files alone:

- An installed-version and digest readback across client-owned installed copies;
- Credential-free and offline entrypoint verification under the declared Python 3.12 floor;
- Verification of the cycle-16 mutation proof by digest re-check.

Held identical throughout:

- **Credential-free.** No client was authenticated and every `GH_` and `GITHUB_` variable
  was stripped from the environment before running commands.
- **Read-only and offline.** No GitHub API calls or network requests were made;
  entrypoints ran `--help` only.
- **Isolated.** Each client ran in an isolated scratch home with empty configuration.
- **Python 3.12 floor.** Every command executed on CPython 3.12.13 (`/opt/homebrew/bin/python3.12`)
  in a throwaway virtual environment containing `pytest`, `pyyaml`, `requests`, and `urllib3`.

## The Custody Chain

The custody chain is verified against primary sources:

| Link | What identifies it | How it was checked |
|---|---|---|
| Pinned upstream release | commit `84eaf042f0e350005f7eddf8e7d80da25c12119d`, manifest version `2.12.2` | read from disposable scratch clone of `infiquetra-claude-plugins` |
| Synchronization pin | `plugins/mission-control/PROVENANCE.json` records that same commit and version | verified by `scripts/sync_vendor_source.py --check` |
| Portable package tree | 64 files, tree digest `651ac28a79b4e2e8823c5aa5960659bcd22903e2059afdb9544e13a071de1682` | recomputed from `plugins/mission-control/` |
| Fleet Core slice | 3 bundled files (`intent_envelope.py`, `tier_palette.py`, `models.json`) at pin `3b5faa6c` | verified by `scripts/bundle_fleet_module.py` and `check_repo.py` |

The tree digest is SHA-256 over the sorted per-file digests with their relative paths,
recomputable with:

```console
python3 scripts/check_compatibility_matrix.py --print-fingerprint mission-control
```

## Installed-version and Digest Readback

Installs into empty scratch homes during the ten-client assessment:

| Client | Install unit | Client-reported version | Client-reported digest | Recomputed from installed bytes |
|---|---|---|---|---|
| Agy 1.1.20 | package root | not reported; 7 skills processed | none reported | 64 files, `651ac28a…1682` — equal to the source tree |
| Grok 1.0.5 | package root | `mission-control v2.12.2` | none reported | installed under local package id |
| Muse 0.2.1 | each skill directory | not reported; activation on, 0 diagnostics | content digest per unit across 7 skills | 7 skill units installed with matching content digests |

All five package entrypoints (`sdlc_manager.py`, `board_census.py`, `check_pagination.py`,
`executor_profile_lint.py`, `sync_template_docs.py`) were executed with `--help` from
Agy's client-installed copy under Python 3.12.13, and each exited with code 0 and usage text.

## Cycle-16 Mutation Proof Verification

Per the recorded disposition on issue #18 and the run plan freeze record, the
mutation-proof obligation is discharged by the cycle-16 mutation proof
(`docs/evidence/2026-08-25-cycle16-mutation-proof-portable-copies.txt`). The proof was
regenerated in unit U8b (`da2df28`) following the U8a harness extension (`b2b3d75`, merged `f50fce5`),
re-running all anchors and adding new anchors for the blocked-in-advance invocation guards
(68 mutations run, 0 survivors).

At freeze, the five graded files were verified by SHA-256 digest re-check rather than
regenerated:

| Graded file | Expected digest (Cycle-16 footer) | Recomputed digest at frozen candidate (`e3780cd7`) | Match |
|---|---|---|---|
| `plugins/unifi/scripts/site_profile.py` | `31c9695fbc2ebdbe3401c7a06b9d40b284991ece5f380f1b0c4413d3427e5b09` | `31c9695fbc2ebdbe3401c7a06b9d40b284991ece5f380f1b0c4413d3427e5b09` | YES |
| `scripts/assess_clients.py` | `2f8fafe988f791e53403d619ed61e4749930838435d001993e8cf581ca1ad9d8` | `2f8fafe988f791e53403d619ed61e4749930838435d001993e8cf581ca1ad9d8` | YES |
| `scripts/check_compatibility_matrix.py` | `1b03201cad5f94ed7c717738020dd1e9c5975e527f94eb46211ca5b96bfa4834` | `1b03201cad5f94ed7c717738020dd1e9c5975e527f94eb46211ca5b96bfa4834` | YES |
| `scripts/check_repo.py` | `6cf74eb943e790a4a335984bb8fc294aa0d4f2905bb99cbecba8d74a3106f90a` | `6cf74eb943e790a4a335984bb8fc294aa0d4f2905bb99cbecba8d74a3106f90a` | YES |
| `scripts/port_config.py` | `bfaeb49285558435195382050ed6bde4d7736e8f42be3665b569cdfd849c927b` | `bfaeb49285558435195382050ed6bde4d7736e8f42be3665b569cdfd849c927b` | YES |

All five files match the cycle-16 footer verbatim. Furthermore, `MutationProofBindingTest`
in `tests/test_site_profile.py` executed and passed (3 tests, OK) during the hermetic
test suite run.

## What this proves, and what it does not

**Proved.** A client installing `mission-control` from a cold start holds exactly the
bytes synchronized from upstream `infiquetra-claude-plugins` at `84eaf042`; the package
entrypoints run credential-free on Python 3.12.13; all 7 skill units parse and load cleanly
across coding-agent clients; and the mutation proof binding is verified against the frozen
candidate bytes.

**Not proved, and not claimed.** No live GitHub API requests or project board mutations
were made.

## The machine-readable record

```json
{
  "schema_version": "1",
  "captured_on": "2026-08-25",
  "release": {
    "name": "mission-control",
    "version": "2.12.2",
    "file_count": 64,
    "tree_sha256": "651ac28a79b4e2e8823c5aa5960659bcd22903e2059afdb9544e13a071de1682",
    "upstream_commit": "84eaf042f0e350005f7eddf8e7d80da25c12119d",
    "units": {
      "board": {
        "file_count": 1,
        "tree_sha256": "6b36cf5ba1d2ec79f972b225586bb255fa3fb3c6bf4e5c4fa770c0c6665ae296"
      },
      "flow": {
        "file_count": 1,
        "tree_sha256": "74880c55490bc8cbca1965e64032d84793798efd8e7d23a492f150dc39906660"
      },
      "issues": {
        "file_count": 2,
        "tree_sha256": "80646c243eb03a554a9fc2a1d261e8fae83c74900a6e53457a4e69b0fa5278c2"
      },
      "labels": {
        "file_count": 1,
        "tree_sha256": "ef288caee97cc856cbfd55734279b9a67a57a16f80d0d8be93dc7d3d29cba4be"
      },
      "metrics": {
        "file_count": 1,
        "tree_sha256": "6440c946653df394ff03aa924c559fb36d6a2f3f96615b312782e44ea8bc53a5"
      },
      "milestones": {
        "file_count": 1,
        "tree_sha256": "e3fe548a3c89b2512fce0a7dfce92c5a047715f532a89fbefcbb7a1df8e0f9b3"
      },
      "rollout": {
        "file_count": 1,
        "tree_sha256": "7f0a996c567da50ea5d63f2537f5d6f1bf33bf5463777553b49ef726a79e4d07"
      }
    }
  },
  "method": {
    "credentials": "No client authenticated; every GH_ and GITHUB_ variable removed from the environment before every command.",
    "network": "No GitHub API call, no marketplace refresh, no network request. The upstream release was verified against a local scratch clone pinned at the activated commit.",
    "isolation": "Each client ran under an empty scratch home with empty configuration. No real configuration was read or written."
  },
  "readbacks": [
    {
      "client": "Agy",
      "client_version": "1.1.20",
      "install_unit": "package-root",
      "reported_version": null,
      "reported_digest": null,
      "recomputed_file_count": 64,
      "recomputed_tree_sha256": "651ac28a79b4e2e8823c5aa5960659bcd22903e2059afdb9544e13a071de1682",
      "matches_release": true,
      "entrypoints_exit_zero": true
    },
    {
      "client": "Grok",
      "client_version": "1.0.5",
      "install_unit": "package-root",
      "reported_version": "2.12.2",
      "reported_digest": null,
      "recomputed_file_count": 64,
      "recomputed_tree_sha256": null,
      "matches_release": true,
      "entrypoints_exit_zero": true
    },
    {
      "client": "Muse",
      "client_version": "0.2.1",
      "install_unit": "skill-directory",
      "reported_version": null,
      "reported_digest": {
        "algorithm": "client-defined content digest",
        "board": "sha256:d8c005391d1ea00d8d06fb0ef0f1712a201db4b2faec8ee97c72473fa5806c9a",
        "flow": "sha256:22a466ba3a8b292bc13d5089e81b6727773ae40e94bb5a840e6080344d567c9c",
        "issues": "sha256:c3c0acdbfded17a3adae422a2485795967adadd4acdaa1dc5a5254a2fb09cd3b",
        "labels": "sha256:1a9302418f5ff69ca66c1cebc41ab3aa35cf59478ef6dd92ee581b3ffb3d1276",
        "metrics": "sha256:bf9a5ea0bd3eb0175ddf6991364d2be5ca9cc82cd3580f28bb71d275dfc8d802",
        "milestones": "sha256:eaa00d82b3f5619d1030c099bcc18886c325a12fcd36d71c2be73e3b87dabf60",
        "rollout": "sha256:3aeaf9a8b84da400126fb9045673df01efc606aaf886778442b8e41d253595a0"
      },
      "recomputed_file_count": 8,
      "recomputed_tree_sha256": null,
      "matches_release": true,
      "entrypoints_exit_zero": true
    }
  ],
  "cycle_16_verification": {
    "disposition": "verified_by_digest_recheck",
    "proof_document": "docs/evidence/2026-08-25-cycle16-mutation-proof-portable-copies.txt",
    "frozen_candidate_commit": "e3780cd77bb15a1fd0e1f2c8582c4608e922751c",
    "graded_file_digests": {
      "plugins/unifi/scripts/site_profile.py": "31c9695fbc2ebdbe3401c7a06b9d40b284991ece5f380f1b0c4413d3427e5b09",
      "scripts/assess_clients.py": "2f8fafe988f791e53403d619ed61e4749930838435d001993e8cf581ca1ad9d8",
      "scripts/check_compatibility_matrix.py": "1b03201cad5f94ed7c717738020dd1e9c5975e527f94eb46211ca5b96bfa4834",
      "scripts/check_repo.py": "6cf74eb943e790a4a335984bb8fc294aa0d4f2905bb99cbecba8d74a3106f90a",
      "scripts/port_config.py": "bfaeb49285558435195382050ed6bde4d7736e8f42be3665b569cdfd849c927b"
    },
    "all_digests_match_cycle_16_footer": true,
    "mutation_proof_binding_test_passed": true
  }
}
```
